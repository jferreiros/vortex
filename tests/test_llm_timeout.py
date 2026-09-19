"""The first-token guard: a hung completion must never leave the line silent.

Offline. The LLM service here is the real ``OpenAILLMService`` — so the test
breaks when pipecat changes the shape of ``get_chat_completions`` — with its
OpenAI client replaced by a stand-in that reproduces the 2026-09-18 failure:
the request is accepted, the response headers arrive, and the body never does.
No sockets, no keys, no network.

The deadlines here are a fraction of a second, so the whole file runs in well
under a second even on the retry paths.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from vortex.conversation.prompt import wait_prompt_for
from vortex.line.llm_timeout import (
    ERROR_EVENT,
    RETRY_EVENT,
    TIMEOUT_EVENT,
    first_token_guard,
)

# Long enough that nothing finishes on its own, short enough that a leaked
# await would fail the suite rather than hang it.
FOREVER = 30.0
DEADLINE = 0.15


# --- stand-ins ---------------------------------------------------------------


class Chunk:
    """A chunk of a streamed completion. Only identity matters here."""

    def __init__(self, text: str) -> None:
        self.text = text


class FakeStream:
    """A response whose headers arrived. The body is whatever we say it is.

    ``stall`` is the failure from the post-mortem: the provider answers 200 and
    then writes nothing. ``gap`` is its opposite, a healthy but slow stream: the
    first token is prompt and every chunk after it lands later than the
    first-token deadline. None of those may be cut.
    """

    def __init__(self, chunks: list[Chunk], *, gap: float = 0.0, stall: bool = False) -> None:
        self._chunks = chunks
        self._gap = gap
        self._stall = stall
        self.closed = False

    def __aiter__(self) -> Any:
        return self._body()

    async def _body(self) -> Any:
        if self._stall:
            await asyncio.sleep(FOREVER)
        for index, chunk in enumerate(self._chunks):
            if self._gap and index:
                await asyncio.sleep(self._gap)
            yield chunk

    async def close(self) -> None:
        self.closed = True


class FakeCompletions:
    """``client.chat.completions`` with one scripted behaviour per attempt.

    The last entry repeats, so a one-entry script answers every attempt the
    same way.
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = script
        self.calls = 0
        self.params: list[dict[str, Any]] = []

    async def create(self, **params: Any) -> Any:
        self.calls += 1
        self.params.append(params)
        behaviour = self._script[min(self.calls - 1, len(self._script) - 1)]
        return await behaviour()


def hanging_headers() -> Any:
    """The provider never answers at all: ``create()`` itself never returns."""

    async def behaviour() -> Any:
        await asyncio.sleep(FOREVER)

    return behaviour


def stalled_body(holder: list[FakeStream]) -> Any:
    """200 with the headers, then nothing. The 2026-09-18 failure."""

    async def behaviour() -> Any:
        stream = FakeStream([], stall=True)
        holder.append(stream)
        return stream

    return behaviour


def streaming(chunks: list[Chunk], *, gap: float = 0.0) -> Any:
    async def behaviour() -> Any:
        return FakeStream(chunks, gap=gap)

    return behaviour


def build_llm(
    script: list[Any],
    *,
    timeout: float = DEADLINE,
    retries: int = 1,
    fallback: Any = None,
    retry_model: str | None = None,
) -> tuple[Any, list[tuple[str, dict]], list[Any], FakeCompletions]:
    """A guarded ``OpenAILLMService`` with a scripted client. Nothing connects."""
    pytest.importorskip("pipecat")
    from pipecat.services.openai.llm import OpenAILLMService

    events: list[tuple[str, dict]] = []
    pushed: list[Any] = []

    llm = first_token_guard(OpenAILLMService)(
        api_key="test-key-not-a-secret",
        base_url="http://127.0.0.1:1/v1",
        settings=OpenAILLMService.Settings(model="test-model"),
        first_token_timeout_secs=timeout,
        llm_retries=retries,
        retry_model=retry_model,
        timeout_fallback_text=fallback if fallback is not None else (lambda: wait_prompt_for("es")),
        timeout_log_event=lambda kind, **data: events.append((kind, data)),
    )

    completions = FakeCompletions(script)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    async def record(frame: Any, *args: Any, **kwargs: Any) -> None:
        pushed.append(frame)

    llm.push_frame = record  # type: ignore[method-assign]
    return llm, events, pushed, completions


def a_context() -> Any:
    from pipecat.processors.aggregators.llm_context import LLMContext

    return LLMContext([{"role": "user", "content": "quiero una cita"}])


async def drain(stream: Any) -> list[Any]:
    return [chunk async for chunk in stream]


# --- the failure the guard exists for ----------------------------------------


async def test_a_stalled_body_is_abandoned_retried_and_answered_out_loud() -> None:
    """Accepted, never streamed: the caller hears a line instead of 36 s of nothing."""
    stalled: list[FakeStream] = []
    llm, events, pushed, completions = build_llm([stalled_body(stalled)], retries=1)

    stream = await llm.get_chat_completions(a_context())

    # Nothing came back from the provider, so the turn produces no chunks...
    assert await drain(stream) == []
    # ...but it does produce a sentence, downstream, in the call's language.
    from pipecat.frames.frames import LLMTextFrame

    assert [type(f) for f in pushed] == [LLMTextFrame]
    assert pushed[0].text == wait_prompt_for("es")

    # Two attempts: the first and its one retry, both abandoned on the deadline.
    assert completions.calls == 2
    kinds = [kind for kind, _ in events]
    assert kinds == [TIMEOUT_EVENT, RETRY_EVENT, TIMEOUT_EVENT]
    first = dict(events[0][1])
    assert first["attempt"] == 1
    assert first["attempts"] == 2
    assert first["timeout_secs"] == DEADLINE
    assert first["elapsed_secs"] >= DEADLINE
    assert first["model"] == "test-model"
    assert dict(events[1][1])["attempt"] == 2

    # The abandoned requests released their sockets rather than leaking them.
    assert [s.closed for s in stalled] == [True, True]


async def test_a_request_that_never_answers_at_all_is_abandoned_too() -> None:
    """The stall can also sit before the headers. Same deadline, same ending."""
    llm, events, pushed, completions = build_llm([hanging_headers()], retries=1)

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert completions.calls == 2
    assert [kind for kind, _ in events] == [TIMEOUT_EVENT, RETRY_EVENT, TIMEOUT_EVENT]
    assert pushed[0].text == wait_prompt_for("es")


async def test_the_retry_is_what_answers_when_the_first_attempt_hangs() -> None:
    """One bad request does not cost the turn: the re-issue streams normally."""
    chunks = [Chunk("hola"), Chunk(" buenas")]
    llm, events, pushed, completions = build_llm([stalled_body([]), streaming(chunks)], retries=1)

    got = await drain(await llm.get_chat_completions(a_context()))

    assert got == chunks
    assert completions.calls == 2
    assert [kind for kind, _ in events] == [TIMEOUT_EVENT, RETRY_EVENT]
    # A turn the retry rescued says nothing extra: no holding line.
    assert pushed == []


async def test_the_retry_switches_to_the_alternate_model() -> None:
    """A hang on deepseek must not spend the retry on the same hung slot."""
    chunks = [Chunk("hola")]
    llm, events, pushed, completions = build_llm(
        [stalled_body([]), streaming(chunks)],
        retries=1,
        retry_model="qwen3.6",
    )

    got = await drain(await llm.get_chat_completions(a_context()))

    assert got == chunks
    assert completions.calls == 2
    assert completions.params[0]["model"] == "test-model"
    assert completions.params[1]["model"] == "qwen3.6"
    assert dict(events[1][1])["model"] == "qwen3.6"
    assert llm._settings.model == "qwen3.6"
    assert pushed == []


async def test_the_retry_keeps_the_model_when_the_alt_is_empty_or_the_same() -> None:
    chunks = [Chunk("sí")]
    llm, _events, _pushed, completions = build_llm(
        [stalled_body([]), streaming(chunks)],
        retries=1,
        retry_model="test-model",
    )

    await drain(await llm.get_chat_completions(a_context()))

    assert [call["model"] for call in completions.params] == ["test-model", "test-model"]
    assert llm._settings.model == "test-model"


async def test_retries_can_be_switched_off() -> None:
    """``LLM_RETRIES=0`` is one attempt and straight to the spoken fallback."""
    llm, events, pushed, completions = build_llm([stalled_body([])], retries=0)

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert completions.calls == 1
    assert [kind for kind, _ in events] == [TIMEOUT_EVENT]
    assert pushed[0].text == wait_prompt_for("es")


# --- what the guard must NOT do ----------------------------------------------


async def test_a_slow_but_streaming_answer_is_never_cut() -> None:
    """Only the first token is on the clock.

    The first chunk is prompt and every chunk after it lands later than the
    whole first-token deadline. A request timeout — or an httpx read timeout at
    the same value — would have cut this answer in the middle; the guard must
    not, because a model that is talking slowly is still talking.
    """
    chunks = [Chunk("uno"), Chunk(" dos"), Chunk(" tres")]
    llm, events, pushed, completions = build_llm(
        [streaming(chunks, gap=DEADLINE * 1.5)], timeout=DEADLINE, retries=1
    )

    got = await drain(await llm.get_chat_completions(a_context()))

    assert got == chunks
    assert completions.calls == 1
    assert events == []
    assert pushed == []


async def test_a_prompt_answer_is_untouched() -> None:
    chunks = [Chunk("sí")]
    llm, events, pushed, completions = build_llm([streaming(chunks)])

    assert await drain(await llm.get_chat_completions(a_context())) == chunks
    assert completions.calls == 1
    assert events == []
    assert pushed == []


async def test_a_zero_timeout_hands_the_stream_straight_back() -> None:
    """``LLM_FIRST_TOKEN_TIMEOUT_SECS=0`` restores pipecat's own behaviour."""
    chunks = [Chunk("vale")]
    llm, events, _pushed, completions = build_llm([streaming(chunks)], timeout=0.0)

    stream = await llm.get_chat_completions(a_context())

    assert isinstance(stream, FakeStream)
    assert await drain(stream) == chunks
    assert completions.calls == 1
    assert events == []


async def test_an_empty_but_complete_answer_is_not_a_timeout() -> None:
    """A stream that closes with no chunks answered; it just had nothing to say."""
    llm, events, pushed, completions = build_llm([streaming([])])

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert completions.calls == 1
    assert events == []
    assert pushed == []


# --- errors that are not timeouts --------------------------------------------


async def test_a_failing_provider_is_retried_and_still_says_something() -> None:
    """A 500 ends like a timeout — out loud — but is filed under its own name."""

    def exploding() -> Any:
        async def behaviour() -> Any:
            raise RuntimeError("upstream exploded")

        return behaviour

    llm, events, pushed, completions = build_llm([exploding()], retries=1)

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert completions.calls == 2
    assert [kind for kind, _ in events] == [ERROR_EVENT, RETRY_EVENT, ERROR_EVENT]
    assert "upstream exploded" in dict(events[0][1])["error"]
    assert pushed[0].text == wait_prompt_for("es")


async def test_a_broken_fallback_line_never_ends_the_call() -> None:
    def boom() -> str:
        raise ValueError("no line")

    llm, events, pushed, _completions = build_llm([stalled_body([])], retries=0, fallback=boom)

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert pushed == []
    assert [kind for kind, _ in events] == [TIMEOUT_EVENT]


async def test_a_broken_log_sink_never_ends_the_call() -> None:
    pytest.importorskip("pipecat")
    from pipecat.services.openai.llm import OpenAILLMService

    def boom(kind: str, **data: Any) -> None:
        raise OSError("call log is gone")

    llm = first_token_guard(OpenAILLMService)(
        api_key="test-key-not-a-secret",
        settings=OpenAILLMService.Settings(model="test-model"),
        first_token_timeout_secs=DEADLINE,
        llm_retries=0,
        timeout_fallback_text="Un momento, por favor.",
        timeout_log_event=boom,
    )
    llm._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions([stalled_body([])]))
    )
    pushed: list[Any] = []

    async def record(frame: Any, *args: Any, **kwargs: Any) -> None:
        pushed.append(frame)

    llm.push_frame = record  # type: ignore[method-assign]

    assert await drain(await llm.get_chat_completions(a_context())) == []
    assert pushed[0].text == "Un momento, por favor."


# --- the shape pipecat consumes ----------------------------------------------


async def test_the_replayed_stream_closes_the_way_pipecat_closes_it() -> None:
    """``_process_context`` takes ``__aiter__()``, ``aclose()`` it, then ``close()``.

    Both wrappers have to survive that, or a cancelled turn leaks the socket.
    """
    from vortex.line.llm_timeout import _EmptyStream, _ReplayStream

    inner = FakeStream([Chunk("a"), Chunk("b")])
    inner_iter = inner.__aiter__()
    first = await inner_iter.__anext__()
    replay = _ReplayStream(inner, inner_iter, first)

    chunk_iter = replay.__aiter__()
    assert (await chunk_iter.__anext__()) is first
    await chunk_iter.aclose()
    await replay.close()
    assert inner.closed is True

    empty = _EmptyStream()
    empty_iter = empty.__aiter__()
    with pytest.raises(StopAsyncIteration):
        await empty_iter.__anext__()
    await empty_iter.aclose()
    await empty.close()


# --- the settings and the wiring ---------------------------------------------


def test_the_settings_carry_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from vortex import settings as settings_module

    monkeypatch.delenv("LLM_FIRST_TOKEN_TIMEOUT_SECS", raising=False)
    monkeypatch.delenv("LLM_RETRIES", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LLM_ALT_MODEL", raising=False)
    settings_module.reset_settings()
    defaults = settings_module.Settings()
    assert defaults.llm_first_token_timeout_secs == 8.0
    assert defaults.llm_retries == 1
    described = defaults.describe()
    assert described["llm_first_token_timeout_secs"] == 8.0
    assert described["llm_retries"] == 1
    assert described["llm_max_tokens"] == 320
    assert described["llm_alt_model"] == "qwen3.6"

    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT_SECS", "2.5")
    monkeypatch.setenv("LLM_RETRIES", "3")
    settings_module.reset_settings()
    tuned = settings_module.Settings()
    assert tuned.llm_first_token_timeout_secs == 2.5
    assert tuned.llm_retries == 3
    settings_module.reset_settings()


def test_the_env_example_documents_both_knobs() -> None:
    from pathlib import Path

    text = Path(__file__).resolve().parent.parent.joinpath(".env.example").read_text("utf-8")
    assert "LLM_FIRST_TOKEN_TIMEOUT_SECS=8.0" in text
    assert "LLM_RETRIES=1" in text
    assert "LLM_ALT_MODEL=qwen3.6" in text
    assert "LLM_MAX_TOKENS=320" in text


def test_the_holding_line_exists_in_every_language_we_detect() -> None:
    from vortex.conversation.prompt import GREETINGS, WAIT_LINES

    assert set(WAIT_LINES) == set(GREETINGS)
    for language, line in WAIT_LINES.items():
        # The TTS flushes on sentence boundaries; a fragment would sit unsaid.
        assert line.endswith("."), language
    assert wait_prompt_for("ca") == WAIT_LINES["ca"]
    # An unknown language falls back rather than raising mid-call.
    assert wait_prompt_for("zz") == WAIT_LINES["en"]
