# Research 06 — Google speech stack and the TTS landscape for a Spanish/Catalan phone agent

Date: 2026-09-19. Context: pipecat-ai 1.11, Soniox `stt-rt-v5`, Google Cloud TTS, Twilio Media Streams (8 kHz mu-law), three-minute calls, "Languages" problem (Spanish to Catalan mid-call).

Claims come from the primary docs cited in Sources. Anything I could not confirm is marked UNVERIFIED.

## Summary

- Chirp 3 HD does not speak Catalan, Galician or Basque. Its locale list stops at `es-ES` and `es-US`. That is why the current stack falls back to `ca-ES-Standard-B`, the only Google Catalan voice outside Gemini-TTS.
- Gemini-TTS is the Google upgrade path for Catalan. The Cloud TTS docs list `ca-ES`, `gl-ES` and `eu-ES` as Preview languages, and `es-ES` as GA. It streams over the same Cloud TTS API, outputs MULAW, and takes a style prompt. Pipecat 1.11 ships `GeminiTTSService` with default model `gemini-3.1-flash-tts-preview`.
- Keep Chirp 3 HD for Spanish. It is GA, streams bidirectionally, supports MULAW, `[pause]` markup, `speaking_rate` 0.25–2.0 and IPA custom pronunciations. Price: $30 per 1M characters, first 1M free per month.
- Keep Soniox for STT. It supports `ca`, `es`, `gl`, `eu`, language identification per token, and mu-law 8 kHz input. Google Chirp 3 has `ca-ES` and `es-ES` GA but `gl-ES` and `eu-ES` only in Preview. No neutral benchmark shows Google beating Soniox on Spanish or Catalan; Soniox's own numbers show the opposite.
- Gemini 3.8 Live (GA, 2026-09-15) is a credible speech-to-speech option: 99 languages including `ca`, `gl`, `eu`, `es`, asynchronous function calling, $0.005/min in and $0.018/min out. Pipecat supports it (`GeminiLiveLLMService`). It is a demo branch, not a replacement, because you lose control of verbalization and voice per language.
- Outside Google, only four vendors in this survey speak Catalan: ElevenLabs (Eleven v3 and v3 Conversational only, not Flash v2.5), Azure (`ca-ES-JoanaNeural`, `EnricNeural`, `AlbaNeural`), Amazon Polly (`Arlet`, neural), MiniMax (`language_boost: Catalan`) and OpenAI `gpt-4o-mini-tts` (Whisper language list). Cartesia, Deepgram, Rime, Inworld (UNVERIFIED), Hume, Kokoro, Chatterbox, XTTS, Orpheus and Speechmatics do not.

## Google STT notes

Model and API. `chirp_3` lives only in Speech-to-Text V2. It supports `StreamingRecognize`, `Recognize` and `BatchRecognize`. Regions `us` and `eu` (multi-region) are GA. The docs page was last updated 2026-09-16.

Languages (Chirp 3 page). `es-ES` GA. `ca-ES` GA. `gl-ES` Preview. `eu-ES` Preview. The older V2 "supported languages" table still lists `chirp`, `chirp_2` and (for `es-ES` only) `chirp_telephony`; it does not list `chirp_3` rows for these locales. Treat the Chirp 3 page as the source of truth.

Features. "Speech adaptation (Biasing)" GA, "a dictionary of up to 1,000 phrases". Denoiser GA: "Setting `denoiser_audio=true` can effectively help you reduce background music or noises like rain and street traffic"; "The denoiser can't remove background human voices." "Language-agnostic audio transcription" GA (the model picks the language). Diarization only in `Recognize` and `BatchRecognize`, not streaming. Word-level confidence "isn't truly a confidence score".

Endpointing. Three sensitivity levels: Standard "balances latency and accuracy", Short "reduces the wait time after speech is detected", Supershort "offers the lowest latency and finalizes the result immediately".

Telephony and 8 kHz. The Chirp 3 page does not mention sample rates or telephony. V2 still has a separate `telephony` model "for audio that originates from an audio phone call, typically recorded at an 8 kHz sampling rate". Whether Chirp 3 degrades on 8 kHz mu-law input is UNVERIFIED; the older `chirp_telephony` fine-tune existed for that reason.

Speech adaptation for alphanumerics. Prebuilt class tokens for `es-ES` include `$OOV_CLASS_ALPHANUMERIC_SEQUENCE`, `$OOV_CLASS_ALPHA_SEQUENCE`, `$OOV_CLASS_DIGIT_SEQUENCE`, `$ADDRESSNUM`, `$DAY`, `$FULLPHONENUM`, `$MONEY`, `$OPERAND`, `$PERCENT`, `$POSTALCODE`, `$TIME`, `$YEAR`. The class-token page has no `ca-ES` entries. Boost: "float value greater than 0", "practical maximum limit for boost values is 20". Phrase sets can be inline or resources.

Pipecat. `GoogleSTTService` defaults to `model="latest_long"`, so you must pass `model="chirp_3"`. It takes `languages: Language | List[Language]` ("First language is primary") and `adaptation: dict | SpeechAdaptation`. It reconnects the stream at 4 minutes because Google caps streams at 5 minutes.

Release notes 2025–2026. Chirp 3 GA 2025-10-13 (85+ languages, diarization, language detection, adaptation, denoiser). Public preview in `asia-south1`, `europe-west2`, `europe-west3`, `northamerica-northeast1` on 2025-11-13. No 2026 STT release-note entries were returned by the fetch; UNVERIFIED whether the page has 2026 entries above the fold.

Pricing. The STT pricing page lists V2 "Standard" recognition at $0.016/min for 0–500k minutes, $0.01/min to 1M, $0.008/min to 2M, $0.004/min above. Footnote: "Standard models include: default, command_and_search, latest_short, latest_long, phone_call, video, chirp". The page text I retrieved has no separate `chirp_3` row; third-party pages quote $0.016/min for Chirp 3. Treat the Chirp 3 rate as UNVERIFIED. V1 keeps 60 free minutes per month.

Gemini 3.5 Transcribe (Gemini API, GA 2026-08-26). `gemini-3.5-transcribe` and `gemini-3.5-transcribe-live` (WebSocket). "85+ languages", "mid-session code-mixing", diarization, word timestamps, custom vocabulary. The language table includes `ca-ES`, `gl-ES`, `es-419`, `es-US`; Basque is not listed and `es-ES` is not listed as a separate row (UNVERIFIED whether `es-ES` is folded into `es-419`). Price: $3.50 per 1M audio tokens or $0.005/min in, $21.00 per 1M text tokens out. Google claims "4.0% (streaming) and 2.6% (non-streaming)" average WER. Pipecat exposes it as `GeminiSTTService` (separate from `GoogleSTTService`).

Does Google beat Soniox on noisy Spanish? No public evidence. Soniox's own comparison page (fetched via search snippet; the URL now returns 404) claims Catalan WER 10.7% for Soniox versus 21.7% for Google on real-world YouTube audio — UNVERIFIED and vendor-sourced. Soniox also hosts the "Pipecat STT benchmark" (August 2026, 1,000 samples, semantic WER): Soniox `stt-rt-v5` 1.27% pooled, Google `gemini-3.5-transcribe-live` 2.24%, OpenAI `gpt-realtime-whisper` 2.73%. That dataset is not split by language. Soniox supports `mulaw` at 8000 Hz natively and language identification per token. Price: $0.12 per hour ($0.002/min). Conclusion: keep Soniox.

## Google TTS notes

Voice families (Cloud TTS "Supported voices" page). Standard, WaveNet, Neural2, Studio, Polyglot, Chirp 3: HD, Chirp 3: Instant custom voice, Gemini-TTS.

Chirp 3: HD. Thirty voice styles: Achernar, Achird, Algenib, Algieba, Alnilam, Aoede, Autonoe, Callirrhoe, Charon, Despina, Enceladus, Erinome, Fenrir, Gacrux, Iapetus, Kore, Laomedeia, Leda, Orus, Pulcherrima, Puck, Rasalgethi, Sadachbia, Sadaltager, Schedar, Sulafat, Umbriel, Vindemiatrix, Zephyr, Zubenelgenubi. Voice name format is `locale-model-voice`, for example `es-ES-Chirp3-HD-Kore`. Locale list includes `es-ES` and `es-US` and 50+ others. `ca-ES`, `gl-ES`, `eu-ES` do not appear. Streaming: `StreamingSynthesize` bidirectional; "The first request must contain your config, and then each subsequent request must contain text." Streaming encodings: "ALAW, MULAW, OGG_OPUS and PCM". "SSML tags are not currently supported for streaming requests." Synchronous SSML support since 2025-10-17: `<phoneme>`, `<p>`, `<s>`, `<sub>`, `<say-as>` (plus `speak`, `break`, `audio`, `prosody`, `voice` on the HD page). Pace: `speaking_rate` "from 0.25x (very slow) to 2x (very fast)". Pauses: markup tags `[pause short]`, `[pause long]`, `[pause]`. Custom pronunciations: "IPA or X-SAMPA". Price: $30 per 1M characters, "0 to 1 million characters" free per month. No latency figure in the docs; UNVERIFIED.

Chirp 3: Instant custom voice. Clone from "up to 10 seconds" of reference audio plus a scripted consent recording. Languages include `es-ES` and `es-US`, not Catalan. Streaming supported. $60 per 1M characters. Not useful for this task unless the clinic wants a branded voice.

Gemini-TTS (Cloud TTS API). Models: `gemini-3.1-flash-tts-preview` ("Optimized for Low latency"), `gemini-2.5-flash-tts` (GA), `gemini-2.5-flash-lite-preview-tts`, `gemini-2.5-pro-tts` ("High control for structured workflows"). Languages: `es-ES` GA; `ca-ES`, `gl-ES`, `eu-ES` Preview. Same 30 voice names as Chirp 3 HD. Streaming: "Cloud Text-to-Speech API supports `multiple request multiple response` type streaming" via `streaming_synthesize()`; streaming encodings "PCM (default), ALAW, MULAW, OGG_OPUS"; default 24 kHz. Style prompt: "The prompt field must be set in the first input chunk, because it's ignored in consecutive chunks." Markup tags (`[sigh]`, `[uhm]`, `[whispering]`, `[extremely fast]`) are Preview. Limits: text and prompt "at most 4,000 bytes" each. Multi-speaker on all models. SSML is not documented for Gemini-TTS. Streaming for Gemini TTS arrived 2025-11-07 (Cloud) and 2026-06-17 (`streamGenerateContent`, Gemini API).

Gemini-TTS pricing. Cloud TTS page: 2.5 Flash TTS $0.50 per 1M text tokens in, $10.00 per 1M audio tokens out. 3.1 Flash TTS (Preview) and 2.5 Pro TTS $1.00 in, $20.00 out. "Audio tokens correspond to 25 tokens per second of audio", so 1 minute = 1,500 audio tokens: about $0.015/min on 2.5 Flash and $0.03/min on 3.1 Flash or 2.5 Pro. No free tier on Cloud. On the Gemini API, `gemini-2.5-flash-preview-tts` and `gemini-3.1-flash-tts-preview` have a free tier; `gemini-2.5-pro-preview-tts` does not.

Standard voices for the three co-official languages. `ca-ES-Standard-B` (female), `gl-ES-Standard-B` (female), `eu-ES-Standard-B` (female). $4 per 1M characters, 4M free per month. No Neural2, WaveNet or Chirp variants exist for these locales.

Pipecat 1.11 classes. `GoogleTTSService` (WebSocket/bidi `StreamingSynthesize`, "lowest latency", default voice `en-US-Chirp3-HD-Charon`, encoding `PCM`, settings `voice`, `language`, `speaking_rate` [0.25, 2.0]). `GoogleHttpTTSService` (unary, `LINEAR16`, `pitch`, `rate`, `volume`, `gender`, `google_style`; "Chirp and Journey voices do not support SSML. The HTTP service automatically uses plain text input for these voices."). `GeminiTTSService` (default model `gemini-3.1-flash-tts-preview`, "which both backends accept", 24 kHz default, `prompt` "Optional style instructions"). The language map in `google/tts.py` includes `Language.CA -> "ca-ES"`, `Language.GL -> "gl-ES"`, `Language.EU -> "eu-ES"`, `Language.ES_ES -> "es-ES"`. Chirp detection is `"chirp" in voice_name.lower()`.

Voice-choice table.

| language | model | voice name | why |
|---|---|---|---|
| es-ES | Chirp 3: HD (GA) | `es-ES-Chirp3-HD-Kore` or `es-ES-Chirp3-HD-Aoede` (female); `es-ES-Chirp3-HD-Charon` or `-Puck` (male) | GA, bidi streaming, MULAW output, `[pause]` markup, `speaking_rate`, IPA pronunciations, 1M free chars. Per-voice Spanish quality is UNVERIFIED; A/B three voices on a phone. |
| es-ES (alternate) | Gemini-TTS `gemini-2.5-flash-tts` (GA) | `Kore` / `Charon` | Style prompt ("habla como recepcionista de clínica, ritmo rápido"), same voices; costs about $0.015/min; jury-friendly. Latency vs Chirp 3 HD is UNVERIFIED. |
| ca-ES | Gemini-TTS `gemini-2.5-flash-tts` (language Preview) | `Kore` / `Charon` | Only Google model with a modern Catalan voice. Same voice identity as Spanish, so the mid-call switch keeps one "person". Preview status is the risk. |
| ca-ES (fallback) | Standard | `ca-ES-Standard-B` | GA, $4/1M, 4M free. Sounds dated; only if Gemini-TTS fails. |
| gl-ES | Gemini-TTS (Preview) or Standard | `Kore` / `gl-ES-Standard-B` | Same trade-off as Catalan. |
| eu-ES | Gemini-TTS (Preview) or Standard | `Kore` / `eu-ES-Standard-B` | Same trade-off as Catalan. |

## Gemini Live notes

Models (Gemini API models page, 2026-09). `gemini-3.8-live` (Stable, 2026-09-15), `gemini-3.8-live-extended-thinking` (Stable), `gemini-3.1-flash-live-preview` (Preview, 2026-03-26), `gemini-2.5-flash-native-audio-preview-12-2025` (Preview). There is no model named "Gemini 3 Live"; the 3.x line went 3.1 Flash Live then 3.8 Live.

Capabilities. "99 languages" including `ca`, `gl`, `eu`, `es`. Voices: "any of the voices available for our Text-to-Speech (TTS) models". Function calling: Gemini 3.8 Live "Asynchronous function calling... Supported (default)"; Extended Thinking "Only NON_BLOCKING execution is supported"; 3.1 Flash Live "Function calling is sequential only." Input "raw, little-endian, 16-bit PCM... natively 16kHz"; output "always uses a sample rate of 24kHz". "Audio-only sessions are limited to 15 minutes" (fine for three-minute calls). VAD, affective dialog, proactive audio, thinking levels on Extended Thinking.

Pricing (Gemini API). 3.8 Live: input $0.75/1M text, $3.00/1M audio "or $0.005/min"; output $4.50/1M text, $12.00/1M audio "or $0.018/min". Free tier available. A three-minute call costs about $0.07 in audio. Google claims 3.8 Live Extended Thinking ranks "#1 on Artificial Analysis' Speech-to-Speech leaderboard"; the July 2026 leaderboard I fetched shows it fourth on speech reasoning (98%) behind StepAudio 3 and Qwen models. Latency numbers for 3.8 Live are UNVERIFIED (the leaderboard lists 2.5 Flash Native Audio at 0.63 s time to first audio).

Telephony. The Live API docs have no telephony section. Pipecat bridges it: `TwilioFrameSerializer` converts 8 kHz mu-law to PCM and back, and the transport resamples to 16 kHz in and from 24 kHz out. Google names Pipecat as a launch partner for 3.8 Live.

Pipecat. `GeminiLiveLLMService` (`pipecat-ai[google]`), default model `models/gemini-2.5-flash-native-audio-preview-12-2025`, "supports Gemini 2.5, Gemini 3.x, and the 3.8 Live family". Configure via `GeminiLiveLLMService.Settings(voice=..., language=..., vad=..., thinking=...)`. "Functions registered with `cancel_on_interruption=False` use Gemini's NON_BLOCKING tool mechanism." The supported-services index lists the class as `GeminiLiveS2SService` and `GeminiLiveVertexAIS2SService`; the API page uses `GeminiLiveLLMService`. Check the installed package for the exact name.

Verdict for a booking task. Credible for a demo branch: one WebSocket, async tools, native Catalan. Not credible as the main pipeline this week: you cannot force "quince de octubre" verbalization, you cannot pin a voice per language, Catalan output quality is unmeasured, and every retry costs a whole call. The cascaded pipeline keeps deepseek-v4-flash, the scripted verbalization and the tested prompts.

## Other Google libs

- Speech adaptation classes: see STT notes. Use `$FULLPHONENUM`, `$OOV_CLASS_ALPHANUMERIC_SEQUENCE` and `$DAY`/`$MONTH`-style tokens only for `es-ES`; no class tokens for `ca-ES`.
- Address Validation API covers Spain: "ES | Spain | ⬤". Places API (New) Autocomplete: `POST https://places.googleapis.com/v1/places:autocomplete` with `input`, `locationBias`, `includedRegionCodes` (up to 15) and `languageCode` (BCP-47). Use it to normalize a spoken Madrid address before read-back.
- Gemma 4 (2026-04-02, Apache 2.0): E2B, E4B and 12B accept audio; "Audio supports a maximum length of 30 seconds"; 16 kHz float mono; 25 tokens per second. Trained for "multilingual speech recognition" and translation; per-language list not published. Not a real-time STT; skip.
- Gemma 3n (2025-06-26): USM-based audio encoder, on-device via MediaPipe LLM Inference API (Android, Web), clips up to 30 seconds. Skip for a server agent.
- Google AI Edge: same on-device stack; no server API.
- Noise suppression: Google publishes no standalone denoise API. The Meet Media API only lets you "Consume video streams. Consume audio streams. Consume participant metadata." The only Google denoiser you can call is `denoiser_config` inside Chirp 3 STT. Soniox already claims robustness to noisy telephony audio.
- Lyria: `lyria-3-clip-preview`, `lyria-3.5`, Lyria RealTime. Music only. Irrelevant.

## TTS vendor table

Prices are pay-as-you-go list prices. "ca" means Catalan voice availability. TTFB values are vendor claims unless noted.

| vendor | model | es | ca | TTFB | streaming | price | pipecat class | URL |
|---|---|---|---|---|---|---|---|---|
| Google | Chirp 3: HD | yes (es-ES, es-US) | no | UNVERIFIED | bidi WebSocket, MULAW | $30/1M chars, 1M free | `GoogleTTSService` | docs.cloud.google.com/text-to-speech/docs/chirp3-hd |
| Google | Gemini-TTS 2.5 Flash / 3.1 Flash preview | yes (GA) | yes (Preview), also gl, eu | UNVERIFIED | bidi, MULAW | ~$0.015/min (2.5 Flash), ~$0.03/min (3.1) | `GeminiTTSService` | docs.cloud.google.com/text-to-speech/docs/gemini-tts |
| Google | Standard | yes | yes (`ca-ES-Standard-B`), gl, eu | n/a | HTTP | $4/1M, 4M free | `GoogleHttpTTSService` | docs.cloud.google.com/text-to-speech/docs/list-voices-and-types |
| ElevenLabs | Eleven v3 Conversational | yes | yes (74 langs, `cat`, `glg`; no Basque) | "~280ms" | WebSocket | $0.05/1k = $50/1M | `ElevenLabsDialogueTTSService` | elevenlabs.io/docs/overview/models |
| ElevenLabs | Flash v2.5 | yes | no (32 langs; Catalan absent) | "~75ms" model | WebSocket, `ulaw_8000` | $0.05/1k = $50/1M | `ElevenLabsTTSService` (default) | elevenlabs.io/pricing/api |
| Cartesia | Sonic 3.6 | yes | no (44 langs) | "fastest" (no figure on docs) | WebSocket, word timestamps | plans: $49 = 1.25M credits; ~$37/1M if 1 credit = 1 char (UNVERIFIED) | `CartesiaTTSService` | docs.cartesia.ai/build-with-cartesia/tts-models/latest |
| Deepgram | Aura-2 | yes (`aura-2-nestor-es`, `carina`, `alvaro`, `diana`, `agustina`, `silvia`) | no | UNVERIFIED | HTTP/WS, `mulaw` 8000 native | $0.030/1k = $30/1M | `DeepgramTTSService` | developers.deepgram.com/docs/tts-models |
| Rime | Arcana v3 / Mist v3 / Coda | yes | no (10 langs) | "~200ms TTFB via cloud API" | WebSocket, word timestamps | Mist v3 $0.03/1k, Coda $0.05/1k; Arcana UNVERIFIED | `RimeTTSService` | rime.ai/resources/arcana-v3 |
| OpenAI | gpt-4o-mini-tts | yes | yes (Whisper list: Catalan, Galician; no Basque) | UNVERIFIED | chunked HTTP, `pcm` 24 kHz | $0.60/1M text in + $12/1M audio out | `OpenAITTSService` | developers.openai.com/api/docs/guides/text-to-speech |
| Azure | Neural / DragonHD / MAI-Voice-2 | yes (`es-ES-Ximena:DragonHDLatestNeural`, `es-ES-Marta:MAI-Voice-2-Flash`) | yes (`ca-ES-JoanaNeural`, `EnricNeural`, `AlbaNeural`; gl `SabelaNeural`, `RoiNeural`; eu `AinhoaNeural`, `AnderNeural`) | UNVERIFIED | WebSocket, word timestamps, SSML | pricing page did not render; UNVERIFIED | `AzureTTSService` | learn.microsoft.com/azure/ai-services/speech-service/language-support |
| Amazon Polly | Generative / Neural | yes (generative `Lucia`, `Sergio`) | yes (neural `Arlet`, no generative) | UNVERIFIED | bidi streaming (generative), 8 kHz output | generative $30/1M, neural $16/1M | `AWSPollyTTSService` | docs.aws.amazon.com/polly/latest/dg/generative-voices.html |
| Inworld | TTS-2 / TTS-2 Flash | yes | "200+ languages", list not published; UNVERIFIED | "100 ms" / "20 ms" P90 server-side | WebSocket | $25/1M / $15/1M on demand | `InworldTTSService` | inworld.ai/pricing |
| MiniMax | speech-2.8-turbo | yes | yes (`language_boost: Catalan`) | "under 250 milliseconds" end-to-end (2.6 claim) | HTTP streaming, `pcmu_raw` 8000 | UNVERIFIED | `MiniMaxHttpTTSService` | platform.minimax.io/docs/api-reference/speech-t2a-http |
| Hume | Octave 2 | yes | no (11 langs) | "under 200ms" | yes | $0.15/1k low tiers, $0.05/1k Business | `HumeTTSService` | hume.ai/blog/octave-2-launch |
| Fish Audio | S2.1-Pro | yes | UNVERIFIED (83 langs, list not fetched) | "100ms time-to-first-audio" (S2-Pro) | WebSocket | $15/1M bytes | `FishAudioTTSService` | docs.fish.audio/developer-guide/models-pricing/models-overview |
| Speechmatics | TTS | no (English only) | no | "Sub-150ms" | yes | $0.011/1k | `SpeechmaticsTTSService` | speechmatics.com/text-to-speech |
| Soniox | TTS | UNVERIFIED (60+ langs) | UNVERIFIED | "ultra-low latency" | WebSocket | $4/1M text tokens + $21.50/1M audio tokens (~$0.70/h) | `SonioxTTSService` | soniox.com/docs/tts/get-started |
| PlayHT | Play 3.0 mini | yes | listed in SDK | n/a | n/a | wound down after Meta acquisition, July 2025 (UNVERIFIED) | not in pipecat 1.11 list | play.ht/blog/introducing-play-3-0-mini |
| Kokoro (OSS) | 82M, Apache 2.0 | yes (`e`) | no (9 langs) | fast on CPU | local | free | `KokoroTTSService` | github.com/hexgrad/kokoro |
| Chatterbox Multilingual (OSS) | V3, MIT | yes | no (23 langs) | UNVERIFIED | local | free | `ResembleAITTSService` is the hosted API; local needs your own wrapper | huggingface.co/ResembleAI/chatterbox |
| XTTS v2 (OSS) | Coqui Public Model License | yes | no (16 langs) | UNVERIFIED | local | free (non-commercial license) | `XTTSTTSService`, `XTTSvLLMTTSService` | docs.coqui.ai/en/latest/models/xtts.html |
| Orpheus (OSS) | multilingual research preview, Apache 2.0 | yes | no | "~200ms streaming latency" (vendor) | local | free | none; serve via vLLM | github.com/canopyai/Orpheus-TTS |

## TTS techniques for phone agents

1. Chunk by sentence, not by token. Pipecat default is `TextAggregationMode.SENTENCE`. Keep it for Spanish; Chirp 3 HD and Gemini-TTS render prosody per sentence. Use `TextAggregationMode.TOKEN` only for a measured latency win.
2. Protect numbers and phone numbers from the sentence splitter. Pipecat's `PatternPairAggregator` groups patterns like phone numbers into one chunk.
3. Verbalize in the LLM, not in the TTS. Tell the model: write dates as words ("el quince de octubre a las diez y media"), never digits, slashes or "10:30". Chirp 3 HD in streaming mode ignores SSML, so `<say-as>` is unavailable there. ElevenLabs offers `apply_text_normalization: auto|on|off` as a safety net; Google does not.
4. Add a deterministic normalizer before TTS. `num2words` supports `es`, `ca` and `eu` (not `gl`) with `cardinal`, `ordinal`, `year`, `currency`. Write one function that expands `\d{1,2}/\d{1,2}` into "día de mes" in the active language. Catalan uses "el quinze d'octubre a dos quarts d'onze" or "a les deu i mitja"; pick one register and keep it.
5. Spell emails on read-back. Split as "j, o, a, q, u, i, n, arroba, gmail, punto, com". Insert `[pause short]` (Chirp 3 HD markup) between groups. Read digits in pairs for phone numbers ("seis, cinco, dos, treinta y uno, cero cuatro"). Then confirm with a yes/no question.
6. Speaking rate. Chirp 3 HD `speaking_rate` accepts 0.25–2.0; a phone caller tolerates 1.05–1.15 for confirmations and 1.0 for numbers. Do not exceed 1.2. UNVERIFIED subjective thresholds; test on a real handset.
7. Keep answers short. Three-minute cap plus $0.03/min TTS means every extra sentence costs time, not money. Prompt for one idea per turn and no recap.
8. 8 kHz path. Twilio requires `audio/x-mulaw`, `sampleRate: 8000`, base64, "The audio can be of any size." Two options: ask Google for MULAW 8 kHz in `StreamingSynthesizeConfig`, or let `TwilioFrameSerializer` resample 24 kHz PCM. Prefer the second; one resampler in one place, and `resampler_clear_after_secs` (default 0.2) avoids artefacts at stream restarts. Never resample twice.
9. Downsampling artefacts. Sibilants and "s/f" confusion get worse at 8 kHz. Choose a lower, warmer voice (Charon, Kore) over a bright one. Avoid `speaking_rate` above 1.2; compressed consonants vanish. UNVERIFIED per voice; listen through Twilio, not through the laptop.
10. Pre-generate fixed phrases. Greeting, "un momento", "¿me lo puede repetir?", closing, and the Catalan equivalents. Synthesize once with the same voice and rate, store 24 kHz PCM, and push `TTSAudioRawFrame`s from a small processor keyed by `(text, voice)`. Pipecat 1.11 documents no built-in TTS cache (UNVERIFIED), so this is ten lines of your own code. It removes TTFB on the first turn, where the jury notices.
11. Language switch. Run one `GoogleTTSService` per language and route on the detected language of the last user turn (Soniox gives a `language` field per token). Swapping the `language` and `voice` settings on one service mid-stream is possible but restarts the bidi stream; UNVERIFIED cost.
12. Use interruptions. Send Twilio `clear` on barge-in; pipecat does this through the serializer. Word timestamps (ElevenLabs, Cartesia, Rime) improve context truncation; Google does not return them.

## Recommendation

1. Spanish: stay on Chirp 3 HD via `GoogleTTSService`. Test `es-ES-Chirp3-HD-Kore`, `-Aoede`, `-Charon` through Twilio and keep one. Set `speaking_rate` 1.05.
2. Catalan, Galician, Basque: replace Standard-B with Gemini-TTS `gemini-2.5-flash-tts` through `GeminiTTSService` (same 30 voices, Preview languages). Keep `ca-ES-Standard-B` behind a flag as fallback. If Gemini-TTS Catalan sounds Spanish-accented, the second choice is Azure `ca-ES-JoanaNeural` (mature neural, cheap) and the third is ElevenLabs `eleven_v3_conversational` (~280 ms, $50/1M).
3. ElevenLabs as the Spanish alternate: use `eleven_flash_v2_5` with `output_format=ulaw_8000` only if Google latency disappoints. It cannot do Catalan; keep it Spanish-only.
4. STT: keep Soniox `stt-rt-v5`. Do not switch to Chirp 3 for the four languages. If you want Google STT for a demo, `GoogleSTTService(model="chirp_3", languages=[ES_ES, CA_ES])` with an inline phrase set for clinic names.
5. State-of-the-art angle for the jury: a second branch on `gemini-3.8-live` through `GeminiLiveLLMService` with the same tools. Show it, do not score with it.
6. Ship the verbalization layer (dates, times, digits, email spelling) as code, and unit-test it in `es` and `ca`.

## Sources

- https://docs.cloud.google.com/speech-to-text/docs/release-notes — Chirp 3 GA 2025-10-13; preview regions 2025-11-13.
- https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3 — model `chirp_3`, languages (`ca-ES` GA, `gl-ES`/`eu-ES` Preview), denoiser, adaptation, endpointing levels.
- https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages — older V2 table with `chirp`, `chirp_2`, `chirp_telephony` per locale.
- https://docs.cloud.google.com/speech-to-text/v2/docs/transcription-model — V2 models incl. `telephony` for 8 kHz audio.
- https://docs.cloud.google.com/speech-to-text/v2/docs/adaptation-model — phrase sets, boost up to 20, custom classes.
- https://docs.cloud.google.com/speech-to-text/docs/class-tokens — prebuilt class tokens for `es-ES`; none for `ca-ES`.
- https://cloud.google.com/speech-to-text/pricing — V2 Standard $0.016/min tiered; no `chirp_3` row in retrieved text.
- https://docs.cloud.google.com/text-to-speech/docs/release-notes — Chirp 3 HD SSML (2025-10-17), Gemini TTS streaming (2025-11-07), locales added.
- https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd — voices, locales (no ca/gl/eu), streaming encodings, pause markup, speaking_rate, custom pronunciations.
- https://docs.cloud.google.com/text-to-speech/docs/gemini-tts — models, `ca-ES`/`gl-ES`/`eu-ES` Preview, `es-ES` GA, streaming, prompt rules, 4,000-byte limit.
- https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types — voice families; `ca-ES-Standard-B`, `gl-ES-Standard-B`, `eu-ES-Standard-B`.
- https://docs.cloud.google.com/text-to-speech/docs/chirp3-instant-custom-voice — 10-second clone, consent script, `es-ES` only.
- https://cloud.google.com/text-to-speech/pricing — Chirp 3 HD $30/1M, Instant custom $60/1M, Standard/WaveNet $4/1M, Gemini-TTS token prices, 25 tokens/s.
- https://ai.google.dev/gemini-api/docs/models — model IDs: `gemini-3.8-live`, `gemini-3.1-flash-live-preview`, `gemini-3.1-flash-tts-preview`, `gemini-3.5-transcribe-live`.
- https://ai.google.dev/gemini-api/docs/pricing — Live API and TTS prices; free tiers.
- https://ai.google.dev/gemini-api/docs/live-api/capabilities — 99 languages incl. ca/gl/eu/es, function-calling modes, 16 kHz in / 24 kHz out, 15-minute audio sessions.
- https://ai.google.dev/gemini-api/docs/changelog — 3.8 Live GA 2026-09-15, 3.5 Transcribe GA 2026-08-26, 3.1 Flash TTS 2026-04-15, TTS streaming 2026-06-17.
- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview — March 2026 preview, function calling supported, token limits.
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe — 85+ languages incl. `ca-ES`, `gl-ES`; code-mixing, diarization.
- https://ai.google.dev/gemini-api/docs/speech-generation — Gemini API TTS voices, streaming from 3.1, 24 kHz PCM, 32k context.
- https://blog.google/innovation-and-ai/technology/developers-tools/build-real-time-voice-applications-gemini-audio/ — 3.8 Live launch, $0.005/min in, $0.018/min out, Pipecat partner.
- https://deepmind.google/models/model-cards/gemini-3-1-flash-audio/ — Flash Live/TTS model card, March–April 2026.
- https://artificialanalysis.ai/speech-to-speech — July 2026 S2S leaderboard; Gemini 3.8 Live Extended Thinking fourth on reasoning.
- https://ai.google.dev/gemma/docs/capabilities/audio — Gemma 4 audio: 30 s max, 16 kHz, 25 tokens/s.
- https://developers.googleblog.com/en/introducing-gemma-3n/ — Gemma 3n on-device audio.
- https://developers.google.com/workspace/meet/media-api/guides/overview — Meet Media API consumes streams; no denoise API.
- https://ai.google.dev/gemini-api/docs/music-generation — Lyria models; music only.
- https://developers.google.com/maps/documentation/address-validation/coverage — Spain covered.
- https://developers.google.com/maps/documentation/places/web-service/place-autocomplete — Places API (New) Autocomplete request shape.
- https://docs.pipecat.ai/api-reference/server/services/s2s/gemini-live — `GeminiLiveLLMService`, settings, 3.8 Live support, NON_BLOCKING tools.
- https://docs.pipecat.ai/api-reference/server/services/tts/google — `GoogleTTSService`, `GoogleHttpTTSService`, `GeminiTTSService`; SSML note.
- https://reference-server.pipecat.ai/en/stable/_modules/pipecat/services/google/tts.html — language map (ca/gl/eu), bidi `streaming_synthesize`, Chirp detection.
- https://reference-server.pipecat.ai/en/stable/api/pipecat.services.google.tts.html — `GeminiTTSService` default `gemini-3.1-flash-tts-preview`; `speaking_rate` range.
- https://docs.pipecat.ai/server/services/stt/google — `GoogleSTTService` default `latest_long`, `languages`, `adaptation`, 4-minute reconnect; `GeminiSTTService`.
- https://docs.pipecat.ai/server/services/supported-services — full TTS and S2S class list in pipecat 1.11.
- https://docs.pipecat.ai/pipecat/learn/text-to-speech — `TextAggregationMode.SENTENCE`/`TOKEN`, `PatternPairAggregator`, WebSocket latency advice.
- https://docs.pipecat.ai/server/services/serializers/twilio — 8 kHz mu-law conversion, `resampler_clear_after_secs`.
- https://www.twilio.com/docs/voice/media-streams/websocket-messages — `audio/x-mulaw`, 8000 Hz, base64, mark/clear.
- https://docs.pipecat.ai/server/services/tts/elevenlabs — classes, default `eleven_flash_v2_5`, v3 models, 32 vs 74 languages.
- https://docs.pipecat.ai/server/services/tts/cartesia — default `sonic-3.6`, `max_buffer_delay_ms`, speed/emotion.
- https://docs.pipecat.ai/server/services/tts/azure — `AzureTTSService`, SSML rate/pitch/style.
- https://docs.pipecat.ai/server/services/tts/aws — `AWSPollyTTSService`, engines, 16 kHz internal.
- https://docs.pipecat.ai/server/services/tts/minimax — `MiniMaxHttpTTSService`, default `speech-2.8-turbo`, `language_boost`.
- https://elevenlabs.io/docs/overview/models — v3 70+ langs incl. `cat`, `glg`; Flash v2.5 32 langs without Catalan; v3 Conversational ~280 ms.
- https://elevenlabs.io/pricing/api — $0.05/1k Flash/Turbo/v3 Conversational; $0.10/1k v3 and Multilingual v2.
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert — `ulaw_8000`, `pcm_8000`, `apply_text_normalization`, pronunciation dictionaries.
- https://docs.cartesia.ai/build-with-cartesia/tts-models/latest — Sonic 3.6, 44 languages, no Catalan.
- https://cartesia.ai/pricing — plan credits ($49 = 1.25M, $299 = 8M).
- https://developers.deepgram.com/docs/tts-models — Aura-2 es-ES voices; no Catalan.
- https://developers.deepgram.com/docs/tts-media-output-settings — `mulaw` at 8000 Hz.
- https://deepgram.com/pricing — Aura-2 $0.030/1k characters.
- https://www.rime.ai/resources/arcana-v3 — 2026-02-04, 10 languages, ~200 ms TTFB cloud, Pipecat support.
- https://www.rime.ai/pricing — Mist v3 $0.03/1k, Coda $0.05/1k.
- https://developers.openai.com/api/docs/guides/text-to-speech — Whisper language list incl. Catalan and Galician; `instructions`; pcm 24 kHz.
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts — ca-ES, gl-ES, eu-ES neural voices; es-ES DragonHD and MAI-Voice-2.
- https://docs.aws.amazon.com/polly/latest/dg/generative-voices.html — es-ES generative Lucia/Sergio, bidi streaming, 8 kHz output.
- https://aws.amazon.com/polly/pricing/ — Standard $4, Neural $16, Generative $30 per 1M.
- https://aws.amazon.com/about-aws/whats-new/2022/03/amazon-polly-offers-neural-tts-voices-catalan-mexican-spanish — Arlet Catalan neural voice.
- https://inworld.ai/pricing and https://inworld.ai/tts — TTS-2 $25/1M, TTS-2 Flash $15/1M, TTFB claims, "200+ languages".
- https://platform.minimax.io/docs/api-reference/speech-t2a-http — `language_boost` includes Catalan and Spanish; `pcmu_raw`; 8000 Hz.
- https://www.hume.ai/blog/octave-2-launch and https://www.hume.ai/pricing — 11 languages, <200 ms, $0.15/1k.
- https://docs.fish.audio/developer-guide/models-pricing/models-overview — S2.1-Pro 83 languages, 100 ms TTFA.
- https://www.speechmatics.com/text-to-speech — English only, sub-150 ms, $0.011/1k.
- https://soniox.com/docs/stt/concepts/supported-languages — Catalan, Spanish, Galician, Basque supported.
- https://soniox.com/docs/stt/rt/real-time-transcription — mulaw/alaw at 8000 Hz, language hints, language identification, endpointing.
- https://soniox.com/pricing — real-time STT $0.12/hr; TTS token prices.
- https://soniox.com/benchmarks — Pipecat STT benchmark (Aug 2026), Soniox 1.27% vs Google 2.24% pooled semantic WER.
- https://soniox.com/compare/soniox-vs-google/catalan — Catalan WER 10.7% vs 21.7% (search snippet; page now 404; UNVERIFIED).
- https://soniox.com/docs/tts/get-started — Soniox TTS, 60+ languages, WebSocket.
- https://github.com/hexgrad/kokoro — 9 languages incl. Spanish; no Catalan; Apache 2.0.
- https://huggingface.co/ResembleAI/chatterbox — 23 languages; no Catalan; MIT.
- https://docs.coqui.ai/en/latest/models/xtts.html — XTTS v2 16 languages; no Catalan; Coqui license.
- https://github.com/canopyai/Orpheus-TTS — multilingual research preview incl. Spanish; Apache 2.0.
- https://pypi.org/project/num2words/ — languages `es`, `ca`, `eu` (no `gl`); converters cardinal/ordinal/year/currency.
- https://play.ht/blog/introducing-play-3-0-mini/ — Play 3.0 mini; product status after Meta acquisition UNVERIFIED.
