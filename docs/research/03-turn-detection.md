# Research 03 — Turn detection, endpointing, barge-in and interruptions (Sep 2026)

Scope: pipecat-ai 1.11.0 (verified from the installed package in `vortex/.venv`), Soniox stt-rt-v5, Silero VAD, Twilio 8 kHz mu-law, three-minute calls.
Facts marked VERIFIED come from the installed source or from a fetched primary page. Facts marked UNVERIFIED come from search snippets or from reasoning.

## Summary

- In the team's current mode (`soniox_turn_detection=True`) pipecat installs `ExternalUserTurnStrategies`. Any local VAD start opens a turn and interrupts the bot. The `interrupt_min_words=2` gate in `turns.py` is dead code in this mode. This is the direct cause of noise barge-ins. VERIFIED (source: `pipecat/services/soniox/stt.py`, `pipecat/turns/user_turn_strategies.py`).
- Pipecat 1.11.0 bundles Smart Turn **v3.2** (`smart-turn-v3.2-cpu.onnx`, 8 MB, int8). It resamples 8 kHz to 16 kHz internally with `soxr` since the March 2026 fix. Spanish is supported (v3.1 Spanish accuracy 90.1% on the 8 MB model). `FalSmartTurnAnalyzer` and `UserIdleProcessor` were removed in 1.0.0. VERIFIED.
- `min_volume` cannot separate 5 dB SNR noise from speech. Pipecat maps ITU-R BS.1770 loudness from -110..-10 LUFS to 0..1. `min_volume=0.7` means "louder than -40 LUFS", which street noise at 5 dB SNR passes. A TV is speech, so Silero also fires. Only a word-count gate, a voice-isolation filter, or a noise-trained VAD stops those barge-ins. VERIFIED math, UNVERIFIED on the scorer's audio.
- Filler words hide latency but do not reduce it. Research finds users prefer contextual fillers over silence and rate agents as more responsive. Fillers do not hurt turn detection when you speak them with `TTSSpeakFrame` at function-call start, because pipecat treats them as bot speech. VERIFIED (papers), pipecat behaviour VERIFIED (1.11.0 changelog).
- Recommendation in one line: keep Soniox endpointing for turn end, but replace the start side with `MinWordsUserTurnStartStrategy(min_words=2)` plus `ExternalUserTurnStopStrategy()`, raise `user_idle_timeout` to 5 s with one re-prompt, and instruct the LLM to book the last stated value. Then A/B against VAD mode with Smart Turn v3.2. Details in "Recommendation".

## Options table

| Option | What it does | Languages | Latency | Cost | Pipecat 1.11 support | Source |
|---|---|---|---|---|---|---|
| Smart Turn v3.2 (`LocalSmartTurnAnalyzerV3`) | Audio end-of-turn classifier (Whisper-tiny encoder) on top of VAD. Fires on silence ≥ VAD `stop_secs`, decides "complete/incomplete"; falls back to silence after `SmartTurnParams.stop_secs` (3 s) | 23 incl. Spanish | 12 ms modern CPU, 60 ms cheap AWS | Free, BSD-2 | Bundled; default stop strategy. Resamples 8 kHz | https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview , https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/ |
| Smart Turn on fal.ai (`fal-ai/smart-turn`) | Same model, HTTP. Input `audio_url`, output `prediction`, `probability` | Same | Network round trip added (UNVERIFIED number) | $0.00111 per compute-second (fal pricing API) | `FalSmartTurnAnalyzer` removed in 1.0.0; `HttpSmartTurnAnalyzer(url, aiohttp_session, ...)` remains | https://fal.ai/models/fal-ai/smart-turn/api , CHANGELOG 1.0.0 |
| Soniox endpoint detection | Semantic endpointing inside stt-rt-v5. Emits `<end>` token. Knobs: `endpoint_sensitivity` (-1..1), `endpoint_latency_adjustment_level` (0-3), `max_endpoint_delay_ms` (500-3000) | Soniox multilingual (Spanish yes, UNVERIFIED per-language numbers) | Not published | Included in STT price | `SonioxSTTService(vad_force_turn_endpoint=False, should_interrupt=...)`; installs `ExternalUserTurnStrategies` | https://soniox.com/docs/stt/rt/endpoint-detection , https://docs.pipecat.ai/api-reference/server/services/stt/soniox |
| Deepgram Flux (`flux-general-multi`) | Turn-aware STT: `StartOfTurn`, `EagerEndOfTurn`, `TurnResumed`, `EndOfTurn`. `eot_threshold` 0.5-1.0 (default 0.7), `eager_eot_threshold` 0.3-0.9, `eot_timeout_ms` default 5000. Accepts mulaw 8 kHz | 10 incl. Spanish (GA 29 Apr 2026) | Claims EoT < 400 ms; EagerEndOfTurn 150-250 ms earlier at 50-70% more LLM calls | Promo pricing, not listed | `DeepgramFluxSTTService` with `EagerUserTurnStrategies` | https://developers.deepgram.com/docs/flux/quickstart , https://deepgram.com/learn/introducing-flux-multilingual |
| LiveKit turn detector | Audio model `TurnDetector` v1 / v1-mini (14 languages incl. Spanish); text model `MultilingualModel` (deprecated) 99.3% TP / 86.0% TN for Spanish | 14 | Text model 50-160 ms per turn; audio not published | Free, runs on CPU | Not a pipecat class; port cost is high | https://docs.livekit.io/agents/build/turns/turn-detector/ , https://livekit.com/blog/improved-end-of-turn-model-cuts-voice-ai-interruptions-39 |
| AssemblyAI Universal-Streaming | Semantic + acoustic EoT. `end_of_turn_confidence_threshold` 0.4, `min_turn_silence` 400 ms, `max_turn_silence` 1280 ms; presets aggressive/balanced/conservative | Spanish listed as example | Not published | STT price | `AssemblyAISTTService` (not verified in this study) | https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection |
| Krisp VIVA 2.0 | Turn Prediction v3 (audio only, 12 languages incl. Spanish): 69% of turn-ends caught within 200 ms of silence. Interruption Prediction v1 (English only) separates backchannels from barge-in. Voice isolation before VAD: 3.5x fewer VAD false positives | TP: 12; IP: English | CPU, "real-time" | SDK + API key, pricing not public | `KrispVivaFilter`, `KrispVivaTurn`, `KrispVivaIPUserTurnStartStrategy`, `KrispVivaVadAnalyzer` | https://krisp.ai/blog/voice-ai-turn-taking-interruption-prediction/ , https://docs.pipecat.ai/pipecat/features/krisp-viva |
| Speechmatics | `end_of_utterance_silence_trigger` 0-2 s (0.5-0.8 s for voice AI); semantic turn detection via SLM optional | Multilingual | Not published | STT price | `SpeechmaticsSTTService`, default `TurnDetectionMode.EXTERNAL` in 1.11 | https://docs.speechmatics.com/speech-to-text/realtime/turn-detection |
| ElevenLabs Agents | Turn eagerness Eager / Normal / Patient; turn timeout 1-30 s; interruptions on/off | Multilingual | Not published | Platform | n/a | https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow |
| Vapi | `startSpeakingPlan.waitSeconds` 0.4; smart endpointing "livekit" (English) or "vapi" (non-English); `stopSpeakingPlan` numWords 0, voiceSeconds 0.2, backoffSeconds 1 | Any | Not published | Platform | n/a | https://docs.vapi.ai/customization/speech-configuration |
| Retell | `responsiveness` 0-1 (0 adds up to 5.5 s wait), `interruption_sensitivity`, reminder trigger + max count, backchannel words | Any | Not published | Platform | n/a | https://docs.retellai.com/build/conversation-flow/global-setting |
| Silero VAD v6 | Frame VAD, 8 or 16 kHz. v6: 16% fewer errors on noisy real-life data vs v5. ROC-AUC 0.97 on multi-domain set | Any | ~0.4% CPU | Free, MIT | `SileroVADAnalyzer`; bundled file version UNVERIFIED | https://github.com/snakers4/silero-vad/discussions/678 , https://github.com/snakers4/silero-vad/wiki/Quality-Metrics |
| TEN VAD | 306 KB VAD, faster stop detection than Silero; 16 kHz only | Any | RTF 0.009-0.015 | Apache-2.0 + conditions | Community `TenVadAnalyzer` (`pipecat-ten-vad`), "not officially supported" | https://huggingface.co/TEN-framework/ten-vad , https://docs.pipecat.ai/api-reference/server/services/vad/ten-vad |
| ai-coustics Quail VAD 2.0 | Noise-robust VAD built on the enhancement model, no separate denoiser | Any | Real-time | SDK license (key) | `AICQuailVADAnalyzer` (`pipecat.audio.vad.aic_quail_vad`) since 1.4.0 | https://ai-coustics.com/blog/introducing-the-quail-vad-model-robust-voice-activity-detection-for-real-time-audio |
| Picovoice Cobra VAD | 98.9% TPR at 5% FPR vs Silero 87.7% (vendor benchmark) | Any | RTF 0.0004 | Picovoice key | No analyzer; `KoalaFilter` is Picovoice denoise | https://picovoice.ai/blog/best-voice-activity-detection-vad/ |

## Detailed notes

### 1. Pipecat 1.11.0 turn-taking API (VERIFIED from installed source)

Where things live now:

- `pipecat.turns.user_start`: `VADUserTurnStartStrategy`, `TranscriptionUserTurnStartStrategy(use_interim=True)`, `MinWordsUserTurnStartStrategy(min_words, use_interim=True)`, `WakePhraseUserTurnStartStrategy`, `KrispVivaIPUserTurnStartStrategy(model_path, threshold=0.5)`, `ExternalUserTurnStartStrategy(enable_interruptions=True)`.
- `pipecat.turns.user_stop`: `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6, wait_for_transcript=True)`, `TurnAnalyzerUserTurnStopStrategy(turn_analyzer, wait_for_transcript=True)`, `ExternalUserTurnStopStrategy(timeout=0.5, wait_for_transcript=True)`, `EagerUserTurnStopStrategy(match_policy, speculation_timeout=5.0)`, `LLMTurnCompletionUserTurnStopStrategy`, `DeferredUserTurnStopStrategy` / `deferred()`.
- Every strategy accepts `enable_interruptions` (default True) through `**kwargs`.
- Defaults: start `[VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy]`; stop `[TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())]`.
- `LLMUserAggregatorParams`: `audio_idle_timeout=1.0`, `user_turn_strategies=None`, `user_mute_strategies=[]`, `user_turn_stop_timeout=5.0` (safety net), `user_idle_timeout=0` (0 disables), `vad_analyzer=None`.
- Idle: `UserIdleController` starts its timer on `BotStoppedSpeakingFrame`. It cancels on `UserStartedSpeakingFrame` or `BotStartedSpeakingFrame`. It is suppressed while a user turn is open. A `UserIdleTimeoutUpdateFrame` restarts a running timer with a new value at runtime. The event is `on_user_turn_idle` on the user aggregator. `UserIdleProcessor` was removed in 1.0.0 (deprecated 0.0.100).
- `MinWordsInterruptionStrategy` and `PipelineParams.allow_interruptions` were removed in 1.0.0. Use `MinWordsUserTurnStartStrategy` with `user_turn_strategies`.
- `MinWordsUserTurnStartStrategy` counts words only while the bot speaks. After `BotStoppedSpeakingFrame` one word starts a turn. It resets its bot-speaking flag at each user turn start.
- 1.7.0 fixed multi-fragment turns "started by a transcript rather than by a VAD frame — the case for `MinWordsUserTurnStartStrategy`". 1.6.0 fixed `SpeechTimeoutUserTurnStopStrategy` ending a turn mid-utterance. Both fixes are in 1.11.0.

Smart Turn:

- `LocalSmartTurnAnalyzerV3(smart_turn_model_path=None, cpu_count=1, sample_rate=None, params=SmartTurnParams())`. Bundled file: `smart-turn-v3.2-cpu.onnx`. Changelog 0.0.99: v3.2 "has better handling of short utterances, and is more robust against background noise".
- `SmartTurnParams`: `stop_secs=3` (silence fallback), `pre_speech_ms=500`, `max_duration_secs=8` (rolling window).
- Pipecat docs: "Smart Turn Detection requires VAD to be enabled and works best when the VAD analyzer is set to a short `stop_secs` value. We recommend 0.2 seconds".
- 8 kHz: PR #3857 (merged 2 Mar 2026) added `_resample_to_model_rate()` with `soxr`. 1.3.0 lowered the preset to HQ. Before the fix, `audio_in_sample_rate=8000` made the model hear speech at 2x speed. The team's `LINE_SAMPLE_RATE=8000` is safe on 1.11.0. Accuracy on band-limited telephony audio is UNVERIFIED; the v3.1 training partners supplied English and Spanish human audio, source type not stated.
- Accuracy (Daily blog, 3 Dec 2025): English v3.0 88.3% → v3.1 94.7% (8 MB) → 95.6% (32 MB). Spanish v3.0 86.7% → v3.1 90.1% (8 MB) → 91.0% (32 MB). v3.2 numbers not published in the fetched pages.
- fal: the endpoint exists and costs $0.00111 per compute-second. Pipecat 1.11 has no `FalSmartTurnAnalyzer`; `HttpSmartTurnAnalyzer` posts raw bytes and uses `stop_secs` as its HTTP timeout. Wiring fal's `audio_url` JSON contract to `HttpSmartTurnAnalyzer` is UNVERIFIED; local inference is the documented path and is faster.

Soniox mode in pipecat (VERIFIED):

- `vad_force_turn_endpoint=True` (pipecat default): Soniox endpointing off; `VADUserStoppedSpeakingFrame` sends `{"type":"finalize"}`.
- `vad_force_turn_endpoint=False` (team default): Soniox endpointing on. The service proposes turn start on `VADUserStartedSpeakingFrame` (fast path) or on the first token, and proposes turn stop right after the `<end>` finalized transcript. It installs `ExternalUserTurnStrategies(enable_interruptions=should_interrupt)` "unless the user passed their own `user_turn_strategies`".
- `Settings`: `max_endpoint_delay_ms` (500-3000), `endpoint_sensitivity` (-1.0..1.0), `endpoint_latency_adjustment_level` (0-3). Soniox defaults: 2000 / 0.0 / 0. These only apply with `vad_force_turn_endpoint=False`.
- Soniox docs: "Endpoint detection finalizes speech earlier. This reduces latency, but it can also slightly reduce word recognition accuracy".

Eager end of turn: `EagerUserTurnStrategies` works only with services that emit `EagerTranscriptionFrame` (Deepgram Flux, Cartesia turns in 1.11). Soniox has no eager event.

### 2. Alternatives (numbers from primary pages)

- Deepgram Flux: p90 EoT 1.0 s, p95 1.5 s in the Oct 2025 launch post; Flux Multilingual (Apr 2026) claims EoT "in under 400 milliseconds" and "up to 3x lower latency than competing real-time EoT systems". Ten languages including Spanish. Accepts `mulaw` at 8000 Hz. Switching STT this late is high risk; the numbers are here for comparison only.
- LiveKit: the text model gives Spanish 99.3% true-positive and 86.0% true-negative rates. v0.4.1-intl cut false interruptions 39.23% and improved Spanish accuracy 33.88% (Dec 2025). Audio model v1 defaults to `min_delay 0.3 s`, `max_delay 2.5 s`. Not portable to pipecat without work.
- AssemblyAI: balanced preset 400 ms / 1280 ms / 0.4; conservative 800 ms / 3600 ms / 0.7. Useful as a reference for "how long to wait after an ID digit pause".
- Krisp: Turn Prediction v3 catches 47% more turn-shifts within 200 ms at equal FPR vs v2. Interruption Prediction is English only, so it does not help this Spanish task.
- Vapi ships text heuristics: wait 0.5 s after a number, 0.1 s after punctuation, 1.5 s without punctuation. Its `stopSpeakingPlan.numWords` is the same idea as `MinWordsUserTurnStartStrategy`.
- Retell: `responsiveness` 0-1 maps to up to 5.5 s of deliberate wait. Reminder trigger plus max count is the same pattern as `user_idle_timeout` plus a re-prompt counter.
- ElevenLabs: "Patient" mode is the vendor advice for phone numbers and addresses. Turn timeout is 1-30 s.

### 3. Noise-robust VAD

- Pipecat decision rule (VERIFIED): `speaking = confidence >= params.confidence and volume >= params.min_volume`. Volume is BS.1770 integrated loudness, normalized from -110..-10 LUFS to 0..1, then exponentially smoothed (factor 0.2). `min_volume=0.6` ≈ -50 LUFS; `0.7` ≈ -40 LUFS; `0.8` ≈ -30 LUFS. Telephony speech sits near -20..-30 LUFS (UNVERIFIED for the scorer's files). At 5 dB SNR the noise is only 5 dB below speech, so any `min_volume` that admits speech also admits the noise. `min_volume` only helps against quiet room noise.
- Silero: v6 claims 16% fewer errors on noisy real-life data than v5 and ROC-AUC 0.97 vs TEN VAD 0.93 and WebRTC 0.73 on the Silero multi-domain set. On pure-noise datasets Silero v6 scores 0.87 (ESC-50) vs TEN VAD 0.42, i.e. TEN fires far more on non-speech noise. The pipecat bundled `silero_vad.onnx` version is UNVERIFIED; Silero's own vendor tables are also not commensurable with Picovoice's tables.
- TV and nearby conversation are speech. No VAD threshold separates them. Silero's known weak spots: "music with human voice-like instruments, very high pitched voices". Pipecat issue #3036 (open) reports VAD firing on background conversation with `confidence 0.8`, `start_secs 0.3`, `min_volume 0.8` — the same knobs the team already turned.
- Denoise before VAD: Krisp reports 3.5x fewer VAD false positives and 2x WER improvement after its voice isolation (Mar 2025). Pipecat filters: `KrispVivaFilter` (SDK + key), `AICFilter`, `KoalaFilter`, `RNNoiseFilter`. The transport's `audio_in_filter` applies to the stream that both the VAD and Soniox receive; pipecat has no built-in "denoise for VAD only" path. Soniox v5 already handles telephony noise well per the team's notes, so a denoiser risks WER for a VAD gain.
- Noise-trained VAD without denoise: `AICQuailVADAnalyzer` (ai-coustics, license key, 16 kHz model `quail-vad-2.0-xxs-16khz`). Vendor claims only.
- Pyannote: 62% accuracy on UrbanSound8K noise vs Silero 87% in one third-party test (UNVERIFIED). Not a real-time candidate.
- `start_secs` is the cheapest real lever: a 0.3-0.4 s onset requirement drops most transient noise (horns, clatter) but not continuous TV speech.

### 4. Interruptions and what the caller heard

- Pipecat truncates the assistant context to spoken words only when the TTS emits word timestamps: "Services like Cartesia, ElevenLabs, and Rime provide word-level timestamps". Google TTS (Chirp 3 HD) is not in that list; the Google TTS docs page does not mention timestamps. Without timestamps pipecat appends the full sentence after synthesis. UNVERIFIED for the exact 1.11 behaviour on Google, but the docs list is explicit.
- Open bug #4466 (May 2026, pipecat 1.1.0): an interruption drops already-spoken `TTSTextFrame`s from the output clock queue, so the assistant message can be empty. Not confirmed fixed in the 1.11.0 notes.
- Practical rule: keep option read-outs short (max 3 options per sentence) and end each with a pause, so an interruption lands at a sentence boundary and the context stays honest.
- Twilio: the wire `clear` message exists in `TwilioFrameSerializer` and pipecat sends it on interruption. The team reports "clear has no effect" on the scorer. Pipecat still stops queueing audio locally, so the caller hears at most what is buffered downstream. Keep TTS chunks short to keep that buffer small.

### 5. Fillers and backchannels

- The Latency Floor paper (2026) puts the cascade floor near 380 ms vs a 200 ms human gap and lists "filler generation" as perceptual masking, not a real reduction.
- Deepgram (2026): humans gap at 199-242 ms; callers notice near 800 ms; "Shorten your agent's real delay first, then use fillers to smooth over what's left".
- ACM TAP 2025 VR study and the 2025 filler study: users prefer contextual fillers to silence at equal delay; contextual fillers raise perceived competence more than generic ones. Fillers can make 1000 ms feel like 500 ms (UNVERIFIED secondary claim).
- "Thinking While Speaking" (Nov 2025): a small talker model bridges a reasoner's latency at millisecond time-to-first-response with a 6.3% accuracy gap. Too heavy for the hackathon, but the design point stands: speak something grounded within 300 ms.
- Pipecat mechanics: speak the filler with `TTSSpeakFrame` in `on_function_calls_started`, or let the model emit a "preflight" phrase before the tool call. 1.11.0 changelog confirms async tools "keep settling as ordinary tool results" when a handler speaks filler. The filler is bot speech, so `MinWordsUserTurnStartStrategy` guards it like any other bot turn, and the idle timer does not run during it.
- Do not use vocal "um" with Chirp 3 HD; use a short contextual phrase: "Vale, miro la agenda del 15." A phrase that repeats the parsed value doubles as an implicit confirmation.

## Difficult-caller playbook

Problem shape: corrections mid-sentence, interruptions while the agent lists options, eight seconds of silence, a parking digression, an ID stated then contradicted. Score depends on booking the FINAL stated request.

1. Corrections mid-sentence ("el 15, no, el 5"). Do not end the turn on the pause. Soniox semantic endpointing already tolerates "no, wait". Keep `max_endpoint_delay_ms` at 1500 and `endpoint_sensitivity` ≤ 0.3. In VAD mode, `user_speech_timeout` ≥ 1.0 s. Prompt: "When the caller corrects a value, the last value wins. Never argue with an earlier value."
2. Contradicted ID. Prompt: "Read back the final ID once, digit by digit, before you submit." Vendor advice (ElevenLabs "Patient", Vapi 0.5 s after numbers, AssemblyAI conservative preset) agrees: wait longer after digits. If you stay in Soniox mode, raise `max_endpoint_delay_ms` to 2000 for the ID step at runtime via `SonioxSTTService` settings update (UNVERIFIED that the reconnect is cheap; the service reconnects on settings change).
3. Interruptions during option read-out. Gate barge-in on 2 words so "vale" and TV chatter do not stop the bot, but "no, el martes" does. Read at most three options per sentence. Prompt: "If the caller interrupts a list, stop listing and answer what they said."
4. Eight seconds of silence. `user_idle_timeout=5.0`. On `on_user_turn_idle` speak one short re-prompt ("¿Sigue ahí? ¿Le reservo el martes a las 10?"). Count re-prompts; after the second, summarize and submit the best known request. `UserIdleTimeoutUpdateFrame` lets you lengthen the timer after an ID question. The scorer's own hang-up threshold is unpublished (team note), so re-prompt before 8 s.
5. Digression (parking). Prompt: "Answer a side question in one sentence, then return to the open slot: 'Sobre la cita, ¿le va bien el martes?'" Keep tools available so the model does not lose the booking state.
6. Book the final request. Keep a running "draft booking" object in the tool layer (`prepare_booking`). Every correction overwrites a field. Prompt: "Before `submit_action`, state the final date, time and ID in one sentence. Submit only after the caller confirms or after the second idle re-prompt." Full-Duplex-Bench-v3 (Apr 2026) reports self-correction as "the most consistent failure mode" across systems; an explicit last-value rule in the prompt is the cheapest mitigation.
7. Three-minute cap. Every filler and re-prompt costs seconds. Budget: greeting 4 s, per turn ≤ 8 s, two idle re-prompts max.

## Noise-robust VAD notes (settings to try, in order)

1. Keep Silero, keep 8 kHz (256-sample frames are native). Set `confidence=0.8`, `start_secs=0.35`, `stop_secs=0.3`, `min_volume=0.6`. `min_volume` above 0.7 risks dropping soft callers; it does not filter 5 dB SNR noise anyway.
2. Add the word gate (see Recommendation). This is the change that stops TV speech from interrupting.
3. If the scorer's "Noise" audio still trips barge-in, try `KoalaFilter` or `RNNoiseFilter` as `audio_in_filter` and re-measure Soniox WER on the same files. Keep it only if WER does not move.
4. If credits and time allow, trial `AICQuailVADAnalyzer` or `KrispVivaVadAnalyzer` + `KrispVivaFilter`. Both need vendor keys. Krisp's own numbers (3.5x fewer VAD false positives) are the strongest published evidence.
5. Do not switch to TEN VAD: 16 kHz only, community support, and Silero's tables show it fires more on pure noise.

## Recommendation with settings

Order of work, cheapest first. Measure each step on the "Noise" and "Difficult caller" recordings before the next.

Step 1 — Fix the dead gate (Soniox mode, keep Soniox endpointing).

```python
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

strategies = UserTurnStrategies(
    start=[MinWordsUserTurnStartStrategy(min_words=2, use_interim=True, enable_interruptions=True)],
    stop=[ExternalUserTurnStopStrategy(timeout=0.5, wait_for_transcript=True)],
)
LLMUserAggregatorParams(
    vad_analyzer=SileroVADAnalyzer(
        params=VADParams(confidence=0.8, start_secs=0.35, stop_secs=0.3, min_volume=0.6)
    ),
    user_turn_strategies=strategies,
    user_idle_timeout=5.0,
    user_turn_stop_timeout=6.0,
)
```

Why: a user-supplied `user_turn_strategies` overrides the service's `ExternalUserTurnStrategies` (VERIFIED docstring). `MinWordsUserTurnStartStrategy` needs one word after the bot stops and two words while it speaks. Soniox still proposes the stop with `ProposedUserStoppedSpeakingFrame`, which `ExternalUserTurnStopStrategy` resolves. UNVERIFIED: that a turn opened by the word gate plus an external stop finalizes cleanly in every path; run the scripted difficult-caller eval first. If a turn never closes, `user_turn_stop_timeout` (6 s) is the backstop. Keep `should_interrupt=True` on the STT for the fallback path.

Step 2 — Soniox knobs. Keep `max_endpoint_delay_ms=1500`, `endpoint_sensitivity=0.3`, `endpoint_latency_adjustment_level=2`. If the ID gets split, drop sensitivity to 0.0 and level to 1 (UNVERIFIED direction on real files; Soniox says higher values finalize sooner).

Step 3 — Idle and prompts. `user_idle_timeout=5.0`. One re-prompt, then a summary-and-submit on the second idle. Add the "last value wins", "read back the ID once", "three options per sentence", "one-sentence digression answer" rules to the prompt.

Step 4 — Filler. Speak one contextual phrase in `on_function_calls_started` via `TTSSpeakFrame` (append_to_context default True in 1.11). Keep it under 1 s of audio.

Step 5 — A/B VAD mode with Smart Turn v3.2. Set `soniox_turn_detection=False` and:

```python
UserTurnStrategies(
    start=[VADUserTurnStartStrategy(), MinWordsUserTurnStartStrategy(min_words=2)],
    stop=[
        TurnAnalyzerUserTurnStopStrategy(
            turn_analyzer=LocalSmartTurnAnalyzerV3(
                cpu_count=2, params=SmartTurnParams(stop_secs=2.0)
            )
        )
    ],
)
VADParams(confidence=0.8, start_secs=0.3, stop_secs=0.2, min_volume=0.6)
```

Smart Turn v3.2 is "more robust against background noise" and handles the mid-sentence pause acoustically. VAD `stop_secs` must be short (0.2) for Smart Turn; `SmartTurnParams.stop_secs=2.0` caps how long a true pause holds the turn. Pick the mode with fewer false turn ends on the ID and correction clips.

Step 6 — Only if noise still breaks barge-in: `KoalaFilter` / `RNNoiseFilter` on the input, then vendor VADs.

Do not do: switch STT to Flux (the team's Soniox tuning and language switching would restart from zero); use fal for Smart Turn (class removed, local is 12-60 ms); rely on `min_volume` for 5 dB SNR.

## Sources

- https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview — SmartTurnParams defaults, VAD `stop_secs` 0.2 advice.
- https://docs.pipecat.ai/api-reference/server/utilities/turn-management/user-turn-strategies — all start/stop strategy classes and defaults.
- https://reference-server.pipecat.ai/en/stable/api/pipecat.processors.aggregators.llm_response_universal.html — `LLMUserAggregatorParams` fields.
- https://docs.pipecat.ai/api-reference/server/services/stt/soniox — `vad_force_turn_endpoint`, `should_interrupt`, endpoint settings.
- https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer — VADParams defaults, 8 kHz support.
- https://docs.pipecat.ai/pipecat/features/krisp-viva — Krisp classes and model files in pipecat.
- https://docs.pipecat.ai/api-reference/server/services/vad/ten-vad — `TenVadAnalyzer`, 16 kHz only, community support.
- https://docs.pipecat.ai/pipecat/learn/text-to-speech — word timestamps and interruption context (Cartesia, ElevenLabs, Rime).
- https://docs.pipecat.ai/server/services/tts/google — Google TTS services, no timestamp mention.
- https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md — removals in 1.0.0, v3.2 weights in 0.0.99, soxr in 1.3.0, strategy fixes in 1.6.0/1.7.0.
- https://github.com/pipecat-ai/pipecat/releases/tag/v1.11.0 — 1.11.0 notes (Speechmatics external mode, filler with async tools).
- https://github.com/pipecat-ai/pipecat/issues/3844 — Smart Turn v3 8 kHz bug.
- https://github.com/pipecat-ai/pipecat/pull/3857 — the fix, merged 2 Mar 2026, soxr resampling.
- https://github.com/pipecat-ai/pipecat/issues/4466 — interruption drops spoken TTSTextFrames (open, May 2026).
- https://github.com/pipecat-ai/pipecat/issues/3036 — VAD false activations on background conversation (open).
- https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/ — 23 languages incl. Spanish, 12 ms CPU, 8 MB.
- https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/ — v3.1 English 94.7%, Spanish 90.1% (8 MB).
- https://huggingface.co/pipecat-ai/smart-turn-v3 — model card, Whisper-tiny backbone, BSD-2.
- https://fal.ai/models/fal-ai/smart-turn/api — fal input/output schema; pricing via fal API $0.00111/compute-second.
- https://soniox.com/docs/stt/rt/endpoint-detection — `<end>` token, three knobs, defaults 0 / 0.0 / 2000.
- https://developers.deepgram.com/docs/flux/quickstart — Flux models, thresholds, mulaw 8 kHz.
- https://developers.deepgram.com/docs/flux/state — Flux event state machine.
- https://deepgram.com/learn/introducing-flux-conversational-speech-recognition — p90 1.0 s / p95 1.5 s EoT, eager 150-250 ms earlier.
- https://deepgram.com/learn/introducing-flux-multilingual — 10 languages incl. Spanish, "under 400 ms" claim.
- https://docs.livekit.io/agents/build/turns/turn-detector/ — audio v1 (14 languages), text model Spanish 99.3/86.0.
- https://docs.livekit.io/agents/build/turns/ — interruption params (`min_words`, `min_duration`, false interruption resume).
- https://livekit.com/blog/improved-end-of-turn-model-cuts-voice-ai-interruptions-39 — 39.23% fewer false interruptions, Spanish +33.88%.
- https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection — thresholds and presets.
- https://krisp.ai/blog/voice-ai-turn-taking-interruption-prediction/ — Turn Prediction v3 numbers, IP English only (May 2026).
- https://krisp.ai/blog/improving-turn-taking-of-ai-voice-agents-with-background-voice-cancellation/ — 3.5x fewer VAD false positives after BVC.
- https://docs.speechmatics.com/speech-to-text/realtime/turn-detection — silence trigger 0-2 s, 0.5-0.8 s advice.
- https://blog.speechmatics.com/semantic-turn-detection — SLM end-of-turn token approach (May 2025).
- https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow — eagerness modes, turn timeout 1-30 s.
- https://docs.vapi.ai/customization/speech-configuration — waitSeconds 0.4, livekit vs vapi endpointing, stopSpeakingPlan.
- https://docs.retellai.com/build/conversation-flow/global-setting — responsiveness, interruption sensitivity, reminders, backchannel.
- https://github.com/snakers4/silero-vad/discussions/678 — v6 release: 16% fewer errors on noisy data.
- https://github.com/snakers4/silero-vad/wiki/Quality-Metrics — ROC-AUC table incl. TEN VAD and WebRTC; noise-only accuracy.
- https://huggingface.co/TEN-framework/ten-vad — TEN VAD size, RTF, 16 kHz, license.
- https://picovoice.ai/blog/best-voice-activity-detection-vad/ — Cobra vs Silero vs WebRTC TPR at 5% and 1% FPR (vendor).
- https://ai-coustics.com/blog/introducing-the-quail-vad-model-robust-voice-activity-detection-for-real-time-audio — Quail VAD 2.0 claims (no numbers on page).
- https://www.alphaxiv.org/abs/2608.latency-floor-cascade-voice-agents — latency floor ≈380 ms, fillers as perceptual masking.
- https://deepgram.com/learn/voice-ai-latency-why-pauses-read-as-hesitation — 199-242 ms human gaps, 800 ms notice threshold.
- https://arxiv.org/abs/2511.07397 — Thinking While Speaking / ConvFill.
- https://dl.acm.org/doi/10.1145/3841187 — filler strategies in embodied agents (fetch blocked, summary from search).
- https://arxiv.org/abs/2604.04847 — Full-Duplex-Bench-v3: self-correction is the most consistent failure mode.
- https://docs.livekit.io/agents/start/prompting/ — brevity, spell out numbers, one question at a time.
- https://livekit.com/blog/prompting-voice-agents-to-sound-more-realistic — mid-sentence course corrections in bot speech.
- Installed source: `vortex/.venv/lib/python3.14/site-packages/pipecat/` (1.11.0) — turns package layout, Soniox service, VAD math, Smart Turn v3.2 file, idle controller.
- Team code: `vortex/conversation/turns.py`, `vortex/line/pipecat_voice.py` — current settings and wiring.
