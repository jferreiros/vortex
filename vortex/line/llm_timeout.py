"""A first-token deadline for the LLM: the line must never go mute on a hung request.

Post-mortem of the scored run on 2026-09-18: two of twenty calls went silent
for about 36 seconds and the harness cut them. The server log reads
``OpenAILLMService#18 processing time 37.216 s`` with no TTFB at all — the
provider accepted the request and never streamed a token. No 429, no 500, no
traceback. Other pipelines in the same process answered in 0.75 s at that very
moment, so the event loop was fine; the request simply never produced a first
chunk and nothing in the pipeline was watching for that.

Why not pipecat's own guard. ``BaseOpenAILLMService`` takes
``retry_on_timeout`` / ``retry_timeout_secs``, but the deadline wraps only
``client.chat.completions.create(...)`` — the await that ends when the *response
headers* arrive, before a single token. That await returned fine here, so the
built-in would never have fired; and its one retry is re-issued with no
deadline at all, which is the 37-second hang again.

So the guard lives here instead, as a thin subclass of whatever
OpenAI-compatible service the pipeline uses:

- one attempt opens the stream *and* pulls its first chunk under a single
  deadline, so a stall on the headers and a stall on the body both count as
  "no first token";
- a timed-out attempt is abandoned (the stream is closed, the socket released)
  and re-issued, up to ``LLM_RETRIES`` times;
- once the first chunk is in hand the deadline is gone. The rest of the stream
  is replayed untouched, so a slow but streaming answer is never cut — which
  is why this is not a request timeout;
- when every attempt fails, the agent speaks one short line in the language of
  the call and the turn ends normally. The caller hears "one moment, please"
  instead of silence, the line goes into the context as the assistant's reply,
  and the next user turn works.

Every abandoned request is logged as ``llm.timeout`` and every re-issue as
``llm.retry``, both on the call log with the ``call_id``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

log = logging.getLogger(__name__)

# The values a caller that passes neither gets. The pipeline passes
# ``LLM_FIRST_TOKEN_TIMEOUT_SECS`` and ``LLM_RETRIES`` from the settings.
DEFAULT_FIRST_TOKEN_TIMEOUT_SECS = 8.0
DEFAULT_RETRIES = 1

# What the call log carries: one ``llm.timeout`` per abandoned request, one
# ``llm.retry`` per re-issue. ``llm.error`` is the non-timeout twin, so a 500
# that ends the same way is not filed as a timeout.
TIMEOUT_EVENT = "llm.timeout"
RETRY_EVENT = "llm.retry"
ERROR_EVENT = "llm.error"


def timeout_exception_types() -> tuple[type[BaseException], ...]:
    """Everything that means "the provider ran out of time", across SDK families.

    ``asyncio.wait_for`` raises ``TimeoutError``; the OpenAI SDK wraps a
    request-level timeout in ``APITimeoutError``; a timeout while iterating the
    response stream surfaces as the transport's own exception, which belongs to
    whichever of httpx / httpx2 the installed SDK is built on. pipecat keeps
    that pair in ``TIMEOUT_EXCEPTIONS``.
    """
    from openai import APITimeoutError
    from pipecat.utils.http import TIMEOUT_EXCEPTIONS

    return (TimeoutError, APITimeoutError, *TIMEOUT_EXCEPTIONS)


async def _aclose(obj: Any) -> None:
    """Release a stream or an iterator, whatever its SDK named the method.

    Async generators only have ``aclose``; the OpenAI SDK's ``AsyncStream`` has
    both. Closing is best effort: an abandoned request is already lost, and a
    second failure while tidying up must not replace the first one.
    """
    for name in ("aclose", "close"):
        closer = getattr(obj, name, None)
        if closer is None:
            continue
        with contextlib.suppress(Exception):
            result = closer()
            if asyncio.iscoroutine(result):
                await result
        return


class _ReplayStream:
    """The provider's stream with its first chunk pulled early, put back.

    pipecat consumes the stream with ``stream.__aiter__()`` and closes both the
    iterator and the stream afterwards, so this offers the same three things
    the SDK's ``AsyncStream`` does: an ``__aiter__`` that returns an async
    generator (hence has ``aclose``), and an awaitable ``close``.

    Nothing here carries a deadline. The first chunk proved the provider is
    talking; how long the rest takes is the model's business.
    """

    def __init__(self, stream: Any, chunk_iter: Any, first: Any) -> None:
        self._stream = stream
        self._iter = chunk_iter
        self._first = first

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._replay()

    async def _replay(self) -> AsyncIterator[Any]:
        if self._first is not None:
            first, self._first = self._first, None
            yield first
        async for chunk in self._iter:
            yield chunk

    async def close(self) -> None:
        await _aclose(self._iter)
        await _aclose(self._stream)


class _EmptyStream:
    """A completion that produced nothing, shaped like one that did.

    Returned when every attempt timed out. pipecat's ``_process_context`` walks
    it, finds no chunks, and unwinds through its normal path — the response end
    frame is pushed, the aggregators close the turn, and the fallback line this
    class comes with is the assistant's reply for that turn.
    """

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._nothing()

    async def _nothing(self) -> AsyncIterator[Any]:
        return
        yield  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        return None


def first_token_guard(service_cls: type) -> type:
    """Subclass ``service_cls`` with the first-token deadline described above.

    A factory rather than a fixed class so it composes with
    ``observability.tracing.traced_openai_llm_service``, which builds its own
    subclass on top and only overrides ``create_client``.

    Extra constructor keywords, all optional:

    - ``first_token_timeout_secs``: seconds an attempt may go without its first
      chunk. ``0`` disables the guard and restores pipecat's own behaviour.
    - ``llm_retries``: how many times a timed-out request is re-issued.
    - ``retry_model``: model id to switch to on a re-issue. Same host, same
      key. Empty keeps the hung model. Used so a stall on deepseek-v4-flash
      does not spend the retry on the same slot.
    - ``timeout_fallback_text``: the line to speak when every attempt failed.
      A callable is read at fire time, so a mid-call language switch moves it.
    - ``timeout_log_event``: ``ctx.log.event``-shaped sink, ``(kind, **data)``.
    """

    class FirstTokenGuardLLMService(service_cls):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            timeout = float(
                kwargs.pop("first_token_timeout_secs", DEFAULT_FIRST_TOKEN_TIMEOUT_SECS)
            )
            retries = int(kwargs.pop("llm_retries", DEFAULT_RETRIES))
            retry_model = kwargs.pop("retry_model", None)
            fallback = kwargs.pop("timeout_fallback_text", None)
            log_event = kwargs.pop("timeout_log_event", None)
            # After super(): the base constructor builds the client and the
            # frame processor, and nothing it does reads these.
            super().__init__(**kwargs)
            self._first_token_timeout_secs = max(0.0, timeout)
            self._first_token_retries = max(0, retries)
            self._retry_model = str(retry_model).strip() if retry_model else ""
            self._timeout_fallback_text: Callable[[], str] | str | None = fallback
            self._timeout_log_event: Callable[..., None] | None = log_event

        async def get_chat_completions(self, context: Any) -> Any:
            if not self._first_token_timeout_secs:
                return await super().get_chat_completions(context)

            attempts = self._first_token_retries + 1
            attempt = 0
            while attempt < attempts:
                attempt += 1
                started = time.monotonic()
                try:
                    return await self._stream_with_first_token(context)
                except Exception as exc:
                    elapsed = round(time.monotonic() - started, 3)
                    timed_out = isinstance(exc, timeout_exception_types())
                    detail: dict[str, Any] = (
                        {} if timed_out else {"error": f"{type(exc).__name__}: {exc}"}
                    )
                    self._log_llm_event(
                        TIMEOUT_EVENT if timed_out else ERROR_EVENT,
                        attempt=attempt,
                        attempts=attempts,
                        elapsed_secs=elapsed,
                        timeout_secs=self._first_token_timeout_secs,
                        model=self._current_model(),
                        **detail,
                    )
                    if attempt < attempts:
                        switched = self._switch_to_retry_model()
                        self._log_llm_event(
                            RETRY_EVENT,
                            attempt=attempt + 1,
                            attempts=attempts,
                            after_secs=elapsed,
                            **({"model": switched} if switched else {}),
                        )
            return await self._speak_and_give_up()

        def _current_model(self) -> str:
            settings = getattr(self, "_settings", None)
            return str(getattr(settings, "model", "") or "")

        def _switch_to_retry_model(self) -> str:
            """Point the next attempt at ``retry_model`` when it is a real other model.

            Same OpenAI-compatible client: Helmcode qwen3.6 rides the same
            base URL and key as deepseek-v4-flash. A hang that is the model's
            slot, not the host, then has somewhere else to go. No-op when the
            alt is empty or already the current model.
            """
            alt = self._retry_model
            current = self._current_model()
            if not alt or alt == current:
                return ""
            settings = getattr(self, "_settings", None)
            if settings is None:
                return ""
            settings.model = alt
            return alt

        async def _stream_with_first_token(self, context: Any) -> Any:
            """One attempt: open the stream and hold its first chunk, under one deadline.

            The two awaits share a budget because the failure we are guarding
            against can sit on either side of them. Helmcode returned the
            headers straight away and then never wrote a body, so timing only
            the first await — which is all pipecat's ``retry_on_timeout`` does —
            would have watched the wrong one.
            """
            budget = self._first_token_timeout_secs
            deadline = time.monotonic() + budget
            stream = await asyncio.wait_for(super().get_chat_completions(context), timeout=budget)
            chunk_iter = stream.__aiter__()
            try:
                remaining = max(0.05, deadline - time.monotonic())
                first = await asyncio.wait_for(chunk_iter.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                # A complete, empty answer. Odd, but it is an answer: hand it
                # back rather than spending a retry on it.
                return _ReplayStream(stream, chunk_iter, None)
            except BaseException:
                await _aclose(chunk_iter)
                await _aclose(stream)
                raise
            return _ReplayStream(stream, chunk_iter, first)

        async def _speak_and_give_up(self) -> Any:
            """Say one short line, then end the turn with an empty completion.

            The frame goes downstream between the response-start frame
            ``process_frame`` already pushed and the response-end frame it
            pushes when this returns, so the TTS flushes it as one sentence and
            the assistant aggregator writes it into the context. The model's
            next turn therefore sees a reply where the hole was.
            """
            from pipecat.frames.frames import LLMTextFrame

            text = self._fallback_line()
            if text:
                await self.push_frame(LLMTextFrame(text))
            return _EmptyStream()

        def _fallback_line(self) -> str:
            source = self._timeout_fallback_text
            if source is None:
                return ""
            if not callable(source):
                return str(source)
            try:
                return str(source())
            except Exception as exc:  # a dead fallback must not end the call
                log.warning("LLM timeout fallback line failed: %s", exc)
                return ""

        def _log_llm_event(self, kind: str, **data: Any) -> None:
            log.warning("%s: %s %s", self, kind, data)
            sink = self._timeout_log_event
            if sink is None:
                return
            try:
                sink(kind, **data)
            except Exception as exc:  # the call log must not end the call
                log.warning("could not log %s: %s", kind, exc)

    FirstTokenGuardLLMService.__name__ = f"FirstTokenGuard{service_cls.__name__}"
    FirstTokenGuardLLMService.__qualname__ = FirstTokenGuardLLMService.__name__
    return FirstTokenGuardLLMService
