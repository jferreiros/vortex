# Voice tooling research — September 2026

Six parallel research passes over the voice-agent market, September 2025 to
September 2026. Each one answers one question for the Vortex line: what can
we add, swap or tune to pass more of the 18 problems, and what can we cite to
the jury. Every claim without a fetched primary source carries the tag
`UNVERIFIED`. Every source is listed at the end of each document.

Date: 2026-09-19. Stack under study: pipecat-ai 1.11.0, Soniox `stt-rt-v5`,
Silero VAD, Google Chirp 3 HD and ElevenLabs TTS, deepseek-v4-flash, Twilio
Media Streams at 8 kHz µ-law.

## Read this first: the moves, ranked by points per hour

Weights come from `docs/rules.md`. Every private case passed is worth the
problem's full weight, four cases per problem. "In repo" says what already
exists on `main` so nobody rebuilds it.

| # | Move | Problems (weight) | Effort | In repo today | Doc |
| - | --- | --- | --- | --- | --- |
| 1 | Fix the dead interruption gate in Soniox mode. Pass `MinWordsUserTurnStartStrategy(min_words=2)` plus `ExternalUserTurnStopStrategy()` as our own strategies. | 12 (3), 13 (4), 18 (5) | 1 h | Bug. `interrupt_min_words` only runs in VAD mode, which is off. Verified in code, see below. | [03](03-turn-detection.md) |
| 2 | Add Soniox to `make evals-voice` and score entity character error rate on 5 dB clips, not WER. | 12 (3), 18 (5) | 2 h | Gap. The bench mixes noise at 5 dB but compares Deepgram, OpenAI and Cartesia only. | [01](01-noise-suppression.md), [02](02-stt-landscape.md) |
| 3 | Read-back protocol in the prompt: one field per turn, digits in groups of three, "last value wins", read the id back once. | 4 (2), 12 (3), 13 (4) | 1 h | Partial. `validate_national_id` and near-miss candidates exist; the prompt has no read-back rules. | [02](02-stt-landscape.md), [03](03-turn-detection.md), [05](05-structured-data.md) |
| 4 | Spoken-form mapper for dictated email and phone ("arroba", "punto", "guion bajo", "at", "dot"), then `email-validator` and `phonenumbers`. | 4 (2) | 2 h | Gap. No mapper in `vortex/`. | [05](05-structured-data.md) |
| 5 | Extend the Soniox context: letter names in es and ca, "arroba", "punto", email domains, month names, insurer names. | 4 (2), 12 (3) | 30 min | Partial. `stt_context.py` boosts clinic names and services. | [02](02-stt-landscape.md) |
| 6 | Repair a misheard DNI: generate 1-edit digit candidates and keep the one whose check letter matches. Zero ambiguous cases in 2000 ids at one edit. | 4 (2), 12 (3) | 1 h | Partial. The letter is validated; nothing proposes a corrected id. | [05](05-structured-data.md) |
| 7 | Idle handling: re-prompt at 5 s, then summarise and submit on the second idle. | 13 (4) | 30 min | Done on this branch (T59). | [03](03-turn-detection.md) |
| 8 | Outgoing privacy guard: check every TTS text frame for protected ids and phones after normalisation. Block the frame, never the call. | 14 (4) | 1 h | Gap. The rule lives in the prompt only. `evals/corpus/judge.py` already has the matcher. | [05](05-structured-data.md) |
| 9 | Filler phrase at function-call start ("un momento") through `TTSSpeakFrame`. Hides LLM latency, does not confuse the word gate. | all | 30 min | Gap. | [03](03-turn-detection.md) |
| 10 | Trial `AICFilter` (ai-coustics, `quail-ms-l-8khz`, native 8 kHz, 30 ms) behind move 2. Ship only if entity CER drops. | 12 (3), 18 (5) | 2 h | Wired, **default off**. `pipecat-ai[aic]` in deps; `VORTEX_AIC_FILTER` + `AIC_SDK_LICENSE` attach Quail to `audio_in_filter`. Leave off until a REAL T54 entity-CER A/B shows a drop. | [01](01-noise-suppression.md) |
| 11 | CartoCiudad (IGN, free, no key) as the live geocoder. It tolerated "alcla" for Alcalá; Nominatim did not. | 15 (3) | 1 h | Partial. `geo.py` has a gazetteer and a Nominatim hook. CartoCiudad has its own API shape. | [05](05-structured-data.md) |
| 12 | Gemini-TTS (`gemini-2.5-flash-tts`) for Catalan instead of `ca-ES-Standard-B`. | 11 (3), jury | 1 h | Gap. Perceived quality only; the scorer never hears us. | [06](06-google-and-tts.md) |
| 13 | A/B the VAD mode with Smart Turn v3.2 (bundled, 8 MB, Spanish supported, resamples 8 kHz itself). | 13 (4) | 2 h | Gap. | [03](03-turn-detection.md) |
| 14 | Demo branch on Gemini 3.8 Live (speech-to-speech, GA 2026-09-15) with the same tools. Show it, do not score with it. | jury | half a day | Gap. | [04](04-industry-2025-2026.md), [06](06-google-and-tts.md) |

Do moves 1 to 3 today. They cost three hours and touch the three heaviest
audio problems.

## What the research found in our own code

1. **The interruption gate is dead.** `vortex/conversation/turns.py` returns
   `None` for the turn strategies when `soniox_turn_detection` is `True`, the
   default. pipecat's Soniox service then installs
   `ExternalUserTurnStrategies`, which opens a turn on any local VAD start. The
   two-word barge-in bar never runs. A bus, a television or "uh-huh" interrupts
   the agent. Verified against `pipecat/services/soniox/stt.py` and
   `pipecat/turns/user_turn_strategies.py` in the installed 1.11.0.
2. **The voice bench never hears Soniox.** `evals/voice/pricing.yaml` lists
   Deepgram, OpenAI and Cartesia stacks. The production STT is not measured on
   the 5 dB mixtures the bench already builds.
3. **`vad_min_volume=0.7` cannot reject 5 dB noise.** pipecat maps loudness
   from -110 to -10 LUFS onto 0 to 1, so 0.7 means "louder than -40 LUFS".
   Street noise at 5 dB SNR against a -20 dBFS voice passes that bar. Only a
   word gate, a voice-isolation filter or a noise-trained VAD stops it.

## Where the research disagrees with the repo

- **Language hints.** Document 02 proposes `es, ca, en`. The roster says 69 of
  73 public cases are English (`docs/rules.md`). Keep `en, es, ca`. The repo
  wins.
- **Denoise before STT.** `turns.py` says "no denoiser in front of STT" and
  cites Deepgram. Document 01 agrees for generic denoisers: a December 2025
  paper found MetricGAN+ raised WER in 40 of 40 configurations. ASR-trained
  products (Krisp VIVA, ai-coustics Quail) claim 30 to 46 percent WER cuts.
  Only our own bench decides. Nobody ships a filter without move 2.
- **VAD values.** Document 03 proposes `confidence=0.8, start_secs=0.35,
  stop_secs=0.3, min_volume=0.6`. Treat them as a starting point for the A/B,
  not as a finding.

## What to tell the jury

Numbers with a source. The full list is in [04](04-industry-2025-2026.md).

- Voice agents lose to text agents on the same tasks: 31 to 51 percent success
  in voice against 85 percent in text, and 26 to 38 percent with noise and
  accents (tau-Voice, March 2026). Our problems 12, 13 and 18 are that gap.
- Speech-to-speech models top out at 52.1 percent on agentic voice tasks
  (Artificial Analysis, June 2026). LiveKit, Coval and Deepgram recommend the
  cascade for booking. Our architecture is the industry's.
- Under 15 percent of production agents used speech-to-speech in H1 2026
  (Coval).
- Turn detection became a model: Smart Turn v3.1 scores 91.0 percent on
  Spanish (Daily, December 2025). We ship it in pipecat 1.11.
- Entity errors are the top failure: ServiceNow EVA (March 2026) found
  misheard ids cascade into failed authentication. Our check-letter repair and
  read-back are the answer.
- Latency: Daily's 2026 primer calls 1,500 ms voice-to-voice the real target
  and budgets 1,293 ms. ElevenLabs measures P50 680 ms and P95 1,560 ms.
- Healthcare scheduling is a funded category: Assort Health raised $120M at a
  $1.2B valuation (June 2026), Hyro $45M (October 2025). Published resolution
  rates run from 48 to 97 percent.
- Guardrails come in layers, and the backend validates identity and
  authorisation, never the model (Hamming, June 2026; ElevenLabs, August 2025).
  Our tools return typed rejections for that reason.

## Do not spend time on

- Bandwidth extension or batch enhancement APIs (AudioSR, VoiceFixer,
  ElevenLabs Isolation, fal DeepFilterNet3). Batch, GPU-heavy, no ASR gain.
- Switching STT to Deepgram Flux. It has no Catalan and our Soniox tuning
  would restart from zero.
- `FalSmartTurnAnalyzer` and `UserIdleProcessor`. Both were removed in
  pipecat 1.0. Smart Turn runs locally in 12 to 60 ms.
- `dateparser` for relative dates. It returns `None` for "pasado mañana", "el
  jueves que viene" and "this coming Thursday". Keep the LLM intent plus
  deterministic date arithmetic.
- Embedding models for triage. A static-embedding prototype missed a stroke
  red flag. Keep regex red flags, a keyword table and an enum tool.
- Speech-to-speech for scoring. Demo only.
- Cloudflare Workers AI for denoising. It has no such model.

## The six documents

1. [01-noise-suppression.md](01-noise-suppression.md). Filters before STT at
   8 kHz: pipecat's built-ins, Krisp, ai-coustics, RNNoise, DeepFilterNet,
   evidence for and against, a custom filter sketch.
2. [02-stt-landscape.md](02-stt-landscape.md). Real-time STT vendors for
   noisy Spanish and Catalan, alphanumeric features, two-pass and ensemble
   techniques, Soniox settings to change.
3. [03-turn-detection.md](03-turn-detection.md). Turn strategies, Smart Turn
   v3.2, noise-robust VAD, the difficult-caller playbook, fillers, settings.
4. [04-industry-2025-2026.md](04-industry-2025-2026.md). Launches and claims
   by date, speech-to-speech against cascade, techniques to cite, healthcare
   players, jury-ready numbers.
5. [05-structured-data.md](05-structured-data.md). Libraries for DNI/NIE,
   surnames, dictated email and phone, dates, geocoding, constrained outputs,
   triage. Versions checked on PyPI, code tested in a venv.
6. [06-google-and-tts.md](06-google-and-tts.md). Google STT, TTS and Gemini
   Live in 2026, the TTS vendor table for Spanish and Catalan, phone-agent TTS
   techniques.

## Method and caveats

Six agents ran in parallel with web search and fetch, about 300 searches and
250 fetched sources in total. Two of them hit their search budget near the
end, and each says so in its file. Library versions were read from PyPI.
Geocoders were probed live. pipecat class names and signatures were checked
against the installed 1.11.0 in this repo's `.venv`. Prices and model names
are quoted from vendor pages on 2026-09-19 and can change. Nothing here was
measured on the scorer's audio; that is what move 2 is for.
