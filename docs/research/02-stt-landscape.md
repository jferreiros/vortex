# Real-time STT for noisy Spanish/Catalan telephony (Sep 2026)

Research date: 2026-09-19. Scope: a pipecat 1.11 voice agent on Twilio Media Streams (8 kHz mu-law). Claims without a fetched primary source carry the tag UNVERIFIED.

## Summary

- Keep Soniox `stt-rt-v5` as the primary STT. It is the only cheap option ($0.12/hr) with native Spanish + Catalan, built-in language ID, semantic endpointing, and 8 kHz mu-law input.
- The strongest alternative is AssemblyAI Universal-3.5/3.6 Pro streaming. It supports Catalan, mid-sentence code-switching, and free keyterms, at $0.45/hr. It leads the English pipecat benchmark (0.96% pooled WER).
- No independent benchmark exists for Spanish or Catalan telephony at 5 dB SNR. Every noisy-audio number below is English or vendor-published. Build your own 50-clip bench.
- Alphanumerics are the real risk. Deterministic checks (DNI/NIE check letter, 9-digit phone, email regex) catch most STT errors for free. Add a second STT opinion only on entity turns.
- Do not run the pipeline at 8 kHz. Let `TwilioFrameSerializer` upsample to 16 kHz. Silero, Smart Turn v3, and several STT services break at 8 kHz (pipecat issues #3844, #5717).

## Vendor table

Prices are pay-as-you-go streaming, converted to USD per audio hour. "Code-switch" means the model switches language mid-call without reconnecting.

| Vendor | Model | es / ca | Code-switch | Keyterms | 8 kHz in | Price / hr | pipecat class | Source |
|---|---|---|---|---|---|---|---|---|
| Soniox | stt-rt-v5 (2026-06-16) | es yes, ca yes | Yes, native language ID, 60+ langs | `context` object: general/text/terms, 8k tokens | pcm_mulaw 8000 listed for Soniox audio formats; STT page shows only s16le examples (UNVERIFIED for STT) | $0.12 (language ID and formatting bundled) | `SonioxSTTService` | https://soniox.com/docs/stt/models, https://soniox.com/pricing |
| Deepgram | Flux `flux-general-multi` (GA 2026-04-29) | es yes, ca no | Yes, 10 langs (en, es, fr, de, hi, ru, pt, ja, it, nl) | Keyterm prompting, 100 terms / 500 tokens, dynamic updates mid-stream | Various encodings and rates (docs, no explicit mu-law confirmation) | $0.47 (+$0.078 keyterms) | `DeepgramFluxSTTService` (params UNVERIFIED, doc 404) | https://developers.deepgram.com/docs/flux, https://deepgram.com/pricing |
| Deepgram | Nova-3 `language=multi` | es yes; ca only monolingual `language=ca` | Yes, 10 langs in multi mode; ca not in multi | Same keyterm prompting | Yes (UNVERIFIED) | $0.35 promo (regular $0.55) | `DeepgramSTTService` | https://developers.deepgram.com/docs/models-languages-overview |
| AssemblyAI | Universal-3.5 Pro / 3.6 Pro streaming | es yes, ca yes (19 langs) | Yes, native mid-sentence | `keyterms_prompt` 100 terms x 50 chars, included; `prompt` +$0.05/hr beta | pcm_s16le default in pipecat; mu-law not listed | $0.45 (3.6 Pro rate unpublished) | `AssemblyAISTTService` | https://www.assemblyai.com/docs/streaming/multilingual-transcription, https://www.assemblyai.com/pricing |
| AssemblyAI | universal-streaming-multilingual | es yes, ca no (6 langs) | Per turn only, not mid-sentence | Included since Dec 2025 | Same | $0.15 | Same class | Same |
| ElevenLabs | Scribe v2 Realtime (Scribe v2: 2026-01-09) | es yes, ca yes, both in "Excellent" tier | Auto language detection; ranked first on es-en code-switch bench | 50 keyterms x 20 chars (realtime) | `ulaw_8000`, `pcm_8000` accepted | $0.39 API ($0.28 annual business); keyterm surcharge $0.05/hr UNVERIFIED | `ElevenLabsRealtimeSTTService` | https://elevenlabs.io/docs/overview/capabilities/speech-to-text, https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime |
| Speechmatics | Agent STT `linden-1` (Ursa 2 lineage) | es yes, ca yes (Enhanced/Standard, real-time) | Fixed bilingual packs only. Spanish-English exists; no Spanish-Catalan. Melia 1 auto-switches but is batch-only today | Custom dictionary, `sounds_like`, up to 1000 recommended | No. 16 kHz required; 8 kHz session rejected (pipecat #5717) | $1.04 Standard / $1.35 Enhanced (reported, UNVERIFIED) | `SpeechmaticsSTTService` | https://docs.speechmatics.com/speech-to-text/languages, https://docs.speechmatics.com/speech-to-text/features/custom-dictionary |
| Gladia | Solaria-1 real-time (Solaria-3 async, 2026-06-10) | es yes; ca UNVERIFIED (100+ langs, not named) | Yes, `enable_code_switching`, word-level language tags | Custom vocabulary with intensity 0-1 | mu-law 8000 supported | $0.75 Starter, $0.25 Growth; 50 EUR free | `GladiaSTTService` | https://www.gladia.io/blog/code-switching-language-coverage-limitations, https://www.gladia.io/pricing |
| Google | Chirp 3 (Speech v2 streaming) | es yes, ca yes | `language_codes=["auto"]` picks the dominant language, not true switching | Phrase sets up to 1000; class tokens for es-ES | `telephony` model exists for 8 kHz; es-ES support UNVERIFIED | UNVERIFIED (pricing page not fetched) | `GoogleSTTService` | https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3, https://docs.cloud.google.com/speech-to-text/docs/class-tokens |
| Google | gemini-3.5-transcribe-live (Live API, 2026-09-15) | es yes; ca UNVERIFIED (85+ langs) | Auto language ID when `language_codes` empty | 1000 custom vocabulary terms | No. 16 kHz PCM only; 10-minute session cap | Audio input $0.005/min = $0.30 (Live API rate, UNVERIFIED for transcribe-live) | `GeminiSTTService` | https://ai.google.dev/gemini-api/docs/live-api/live-transcribe |
| OpenAI | gpt-live-transcribe / gpt-transcribe (Realtime API) | es yes; ca UNVERIFIED | `languages` list hints; no explicit switching | `prompt` free text | `g711_ulaw` accepted by Realtime API | $0.27 (gpt-transcribe $0.0045/min) | `OpenAISTTService` (segmented); realtime class UNVERIFIED | https://developers.openai.com/api/docs/guides/realtime-transcription, https://developers.openai.com/api/docs/models/gpt-transcribe |
| Cartesia | ink-2 (2026-05-22), ink-preview (2026-09-04) | ink-2 English only; ink-preview adds es; ca no | No | Not documented | Not documented | 3 credits/s ink-2; USD rate per plan UNVERIFIED | `CartesiaSTTService` | https://docs.cartesia.ai/build-with-cartesia/stt-models/latest, https://docs.cartesia.ai/pricing |
| Azure | Speech real-time | es yes; ca UNVERIFIED | Continuous LID switches per utterance, never inside a sentence | Phrase lists | Yes (UNVERIFIED) | Not shown without region; 5 free hours/month | `AzureSTTService` (name UNVERIFIED) | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification |
| AWS | Transcribe streaming | es-ES yes, ca-ES yes (streaming) | Multi-language identification in streaming | Custom vocabulary (batch + streaming for es-ES, ca-ES) | Yes, 8 kHz telephony | $0.60 reported (UNVERIFIED) | `AWSTranscribeSTTService` (name UNVERIFIED) | https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html |
| Mistral | Voxtral Realtime (2026-02-04) | es yes, ca no (13 langs) | No | Not documented | 16 kHz (UNVERIFIED) | $0.36 ($0.006/min); Apache 2.0 weights | `MistralSTTService` | https://mistral.ai/news/voxtral-transcribe-2/ |
| NVIDIA | Nemotron 3.5 ASR streaming 0.6b (2026-06-04) | es-ES yes (4.11% WER), ca no | Auto language ID across 40 locales | Fine-tune only | 16 kHz | Self-host; Together/Baseten host it | `NvidiaSTTService` / Riva (UNVERIFIED) | https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b |
| NVIDIA | Parakeet TDT 0.6b v3 | es yes; ca not listed (25 European langs) | Auto language detection | No | 16 kHz | Self-host | Same | https://perspectives.nvidia.com/nemotron-speech/task/faq/what-are-the-most-production-ready-open-speech-recognition-models-for-european-l/ |
| Kyutai | Kyutai STT (2025-06) | No Spanish (en/fr 1B, en 2.6B) | No | No | No | Self-host | None | https://kyutai.org/stt/ |
| Whisper self-hosted | faster-whisper, whisper-streaming, WhisperLive | es yes, ca yes | No. Without `language`, Whisper translates code-switched audio to English | Initial prompt only | Resample to 16 kHz | GPU cost; 1-2 s latency | `WhisperSTTService` | https://huggingface.co/blog/ServiceNow-AI/code-switching |
| Meta | muse-voice-transcribe-1.0 | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | `MetaSTTService` | https://github.com/pipecat-ai/stt-benchmark |

Credits you already hold:

- Cloudflare Workers AI ($100): `@cf/deepgram/nova-3` at $0.0092/min WebSocket, `@cf/deepgram/flux` WebSocket-only. Keyterm and `language=multi` pass-through: UNVERIFIED. Source: https://developers.cloudflare.com/workers-ai/models/nova-3/, https://developers.cloudflare.com/changelog/post/2025-10-02-deepgram-flux/
- fal.ai ($50): `fal-ai/elevenlabs/speech-to-text/scribe-v2` (batch) and `fal-ai/wizper` (Whisper v3 batch). No realtime STT found on fal. Source: https://fal.ai/models/fal-ai/elevenlabs/speech-to-text/scribe-v2
- Vercel AI Gateway ($50): `google/gemini-3.5-transcribe`, `openai/gpt-4o-transcribe`, `openai/whisper-1` (beta, batch; some streaming behind WebSockets filter). Source: https://vercel.com/docs/ai-gateway/modalities/speech-to-text

## Benchmarks with numbers

### Pipecat STT benchmark (English only, 1,000 clips, 16 kHz, Silero VAD)

Source: https://github.com/pipecat-ai/stt-benchmark and https://www.daily.co/blog/benchmarking-stt-for-voice-agents/ (2026-02-13; table updated later, Soniox cites an August 2026 run). Semantic WER uses Claude as judge. TTFS = time from end of speech to final transcript.

| Model | WER mean | Pooled WER | Perfect | TTFS median | TTFS P99 |
|---|---|---|---|---|---|
| Meta muse-voice-transcribe-1.0 | 0.97% | 0.83% | 89.2% | 392 ms | 1922 ms |
| AssemblyAI universal-3-6-pro | 1.06% | 0.96% | 87.0% | 307 ms | 498 ms |
| Speechmatics linden-1 | 1.21% | 1.05% | 84.5% | 369 ms | 690 ms |
| Azure | 1.21% | 1.18% | 82.9% | 1016 ms | 1791 ms |
| AssemblyAI universal-3-5-pro | 1.44% | 1.22% | 84.7% | 282 ms | 393 ms |
| Cartesia ink-2 | 1.47% | 1.25% | 84.2% | 299 ms | 1584 ms |
| Soniox stt-rt-v5 | 1.34% | 1.27% | 83.3% | 260 ms | 313 ms |
| Soniox stt-rt-v4 | 1.25% | 1.29% | 84.1% | 249 ms | 310 ms |
| Deepgram nova-3-general | 1.71% | 1.62% | 76.5% | 247 ms | 326 ms |
| AWS | 1.68% | 1.75% | 77.4% | 1136 ms | 1897 ms |
| NVIDIA Nemotron 3.0 ASR (en) | 1.90% | 1.95% | 76.1% | 221 ms | 252 ms |
| Google gemini-3.5-transcribe-live | 2.24% | 2.24% | 78.0% | 458 ms | 599 ms |
| OpenAI gpt-realtime-whisper | 2.92% | 2.73% | 72.5% | 740 ms | 1080 ms |
| OpenAI gpt-4o-transcribe | 3.24% | 3.06% | 75.9% | 637 ms | 1655 ms |
| ElevenLabs scribe_v2_realtime | 3.16% | 3.12% | 81.3% | 281 ms | 407 ms |
| Mistral voxtral-mini-transcribe-realtime-2602 | 4.44% | 4.97% | 68.8% | 525 ms | 1913 ms |
| NVIDIA Nemotron 3.5 ASR (multilingual) | 4.54% | 4.58% | 62.0% | 236 ms | 266 ms |

Deepgram Flux and Gladia are absent from this table. The authors state that results "will differ significantly for other languages".

### Artificial Analysis (English, AA-WER v2: AgentTalk 50%, VoxPopuli 25%, Earnings22 25%)

Source: https://artificialanalysis.ai/speech-to-text. Non-streaming top five: Alibaba Fun-Realtime-ASR-preview 1.7%, StepFun StepAudio 3 1.7%, Microsoft MAI-Transcribe-2 2.0%, ElevenLabs Scribe v2 2.2%, Grok Voice Transcribe 2.0 2.3%. The streaming page did not render numbers in my fetch. No Spanish split.

### Multilingual and Spanish numbers

- NVIDIA Nemotron 3.5 ASR: 8.84% WER across 19 locales, 4.11% Spanish (model card).
- Gemini 3.5 Transcribe: 4.0% average WER streaming, 2.6% non-streaming, across 85+ languages (Google blog, 2026-09-15).
- Microsoft MAI-Transcribe-1: 3.8% average WER on FLEURS, 25 languages (Coval, 2026-06-04).
- ElevenLabs Scribe v2: "93.5% accuracy across 30 languages" on FLEURS (vendor claim via Coval).
- Parakeet TDT 0.6b v3: 6.34% average over 25 European languages (NVIDIA).
- Gladia Solaria-3: Spanish WER 9% lower than Solaria-1 on Common Voice 24 (vendor, no absolute number).
- Soniox 60-language YouTube study: English 1.25% vs Deepgram 1.71% vs AssemblyAI 1.74% (vendor). No Spanish split published.

### Code-switching

- ServiceNow benchmark (2026-06-09), Spanish-English, 259 synthetic TTS utterances: ElevenLabs Scribe v2 first, then Gemini 3 Flash, then AssemblyAI Universal-3 Pro. Whisper Large v3 Turbo last: it translates to English. Errors cluster on the English words, not at switch points. Source: https://huggingface.co/blog/ServiceNow-AI/code-switching
- Catalan-Spanish code-switching research (BSC, Interspeech 2025): fine-tuned Whisper with synthetic code-switched data plus the dominant-language token works best. Gladia cites 51-63% WER for prior Catalan-Spanish CS systems. Absolute numbers UNVERIFIED (PDF not parsed). Source: https://arxiv.org/abs/2507.13875
- Speechmatics claims code-switching "35% better than the nearest competitor" (vendor via Coval, UNVERIFIED).

### Noisy audio

- Gladia Solaria-3 "noisy audio" set: 1.4% vs AssemblyAI 2.1% vs Deepgram 3.2% (vendor, dataset not named).
- Krisp VIVA 2.0 in front of any STT: "cuts WER 10-30% on noisy audio" (Krisp claim via Coval).
- Soniox v5 blog claims "substantially better accuracy" on noisy, telephone and far-field audio; no numbers.
- No independent 5 dB SNR Spanish telephony benchmark exists. You must measure.

### Alphanumerics

- Deepgram claims "90%+ alphanumeric accuracy vs 43-58% for competitors". Vendor claim; the benchmark page I fetched does not show the method. UNVERIFIED.
- AssemblyAI claims prompting cuts WER 21% and entity errors on names 49% (vendor docs).
- Auto Review paper (ACL Industry 2025): ASR and Gemini both add or drop digits on long alphanumeric fields. Gemini had high precision but low recall as a checker. Source: https://arxiv.org/abs/2506.05400

## Alphanumeric features per vendor

**Soniox.** The `context` object has `general` (key-value pairs, keep 10 or fewer), `text` (long documents, weak effect), `terms` (exact spellings), `translation_terms`. Hard cap 8,000 tokens (~10,000 chars). The v5 release claims "major improvements in alphanumeric recognition and formatting" for numbers, codes, emails, addresses and product IDs. The docs give no explicit instruction syntax for "output digits". Put format instructions in `general` (for example `"format": "phone numbers as 9 digits, emails lowercase with @"`) and test. Smart formatting is bundled in the price.

**Deepgram.** `keyterm` (Nova-3 and Flux): up to 100 terms, 500 tokens total, +$0.0013/min. Best practice: 20-50 terms, exact casing, no weights. Flux updates keyterms mid-stream via `Configure`. `numerals` and `smart_format` convert Spanish number words to digits in Nova-3 multilingual. Keyterms bias words, not digit strings. A GitHub thread reports Nova-3 `multi` mis-transcribing "cinco por diez" and "ciento cincuenta" with no vendor answer (https://github.com/orgs/deepgram/discussions/1605).

**AssemblyAI.** `keyterms_prompt` (100 terms, 50 chars each, included on U3.5 Pro) plus a free-text `prompt` (~1,500 chars). You can change both mid-session with `UpdateConfiguration`, so you can push "the caller now dictates a DNI" when the flow reaches that state. Docs advise exact spelling and casing and no common words.

**Google Speech v2.** Phrase sets with boost (practical max 20) and prebuilt class tokens. es-ES supports `$OOV_CLASS_ALPHANUMERIC_SEQUENCE`, `$OOV_CLASS_DIGIT_SEQUENCE`, `$OOV_CLASS_FULLPHONENUM`, `$POSTALCODE`, `$MONEY`, `$TIME`. ca-ES is not on the class-token list. Whether Chirp 3 honours class tokens is UNVERIFIED; the docs say availability "varies by model and language". Example phrase: `"mi DNI es $OOV_CLASS_ALPHANUMERIC_SEQUENCE"`.

**ElevenLabs.** `keyterms` on Scribe v2 Realtime: 50 terms, 20 characters each. Batch Scribe v2 accepts 1,000 terms of 50 characters. Extra charge applies (UNVERIFIED amount). Entity detection is a separate add-on.

**Speechmatics.** Custom dictionary with `content` (output spelling) and `sounds_like` (pronunciations). Real-time caches dictionaries after first use. Recommended 1,000 entries, hard cap 20,000.

**Gladia.** `custom_vocabulary` items with `intensity` 0-1.

**OpenAI / Gemini.** Free-text `prompt` (OpenAI) or 1,000 custom vocabulary terms (Gemini Live transcribe). Neither exposes digit-class biasing.

What helps for DNI digits and spelled emails, in practice:

1. Vocabulary boosting helps proper nouns and domains ("gmail", "hotmail", "outlook", "arroba", "punto", "guion bajo"). It does not fix digit confusions like "seis"/"tres" under noise.
2. Number formatting to numerals helps the LLM. Turn it on where the vendor supports Spanish (Soniox bundled, Deepgram `numerals`).
3. Class tokens (Google es-ES) are the only STT-level feature aimed at digit strings. Catalan lacks them.
4. Check digits are your best detector. The DNI letter is `"TRWAGMYFPDXBNJZSQVHLCKE"[number % 23]`; NIE maps X=0, Y=1, Z=2 before the same formula. A mismatch means "ask again", never "guess".
5. Spanish spelling conventions matter: "be de Barcelona", "uve", "i griega", "zeta", "ce", "ge". Give the LLM a letter-name map and add the letter names to `terms`.

## Techniques

**Keep the pipeline at 16 kHz.** `TwilioFrameSerializer` resamples 8 kHz mu-law to the pipeline rate (`twilio_sample_rate=8000`, optional `sample_rate` override). Setting `audio_in_sample_rate=8000` breaks Smart Turn v3 silently (issue #3844) and makes Speechmatics reject the session (issue #5717). Soniox accepts 8000 Hz natively, but Silero and other services want 16 kHz. Sources: https://reference-server.pipecat.ai/en/latest/api/pipecat.serializers.twilio.html, https://github.com/pipecat-ai/pipecat/issues/3844, https://github.com/pipecat-ai/pipecat/issues/5717

**Noise suppression before STT.** Pipecat ships `audio_in_filter` implementations: `KrispVivaFilter` (needs Krisp SDK and model file), `KoalaFilter` (Picovoice key), `RNNoiseFilter`, `NoisereduceFilter` (deprecated since 0.0.85). Krisp claims 10-30% WER reduction on noisy audio. Denoisers can also erase consonants at 5 dB SNR. Bench with and without. Source: https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.filters.html

**Parallel STT ensemble (ROVER-style).** Run two WebSocket streams on the same audio frames. Use the primary (Soniox) for turn-taking and general dialogue. On entity turns compare only the extracted field from both transcripts. Agreement means accept; disagreement means read back and ask. Cost doubles STT (Soniox $0.12 + AssemblyAI $0.45 = $0.57/hr). Pipecat has `ParallelPipeline`; pick one transcript source for the LLM and log the other. Classic ROVER voting needs three systems; two systems only give you a disagreement signal, which is enough here.

**Two-pass re-transcription.** Buffer the raw PCM of the entity utterance (pipecat exposes `InputAudioRawFrame`). Send that WAV to a batch model with keyterms: ElevenLabs Scribe v2 on fal (credits), `google/gemini-3.5-transcribe` via Vercel AI Gateway (credits), or Voxtral Mini Transcribe V2 ($0.003/min). Latency 1-3 s. Hide it behind the confirmation sentence ("Le repito el DNI..."). Scribe v2 ranked first on Spanish-English code-switching and sits in the top tier on Artificial Analysis.

**Audio-native LLM as tie-breaker.** Send the same buffered audio to `gemini-3.8-live` or `gpt-4o-audio` with a constrained prompt: "Output only the 8 digits and the letter, nothing else". Auto Review found that LLMs also add or drop digits on long strings, so use them as a third vote, never as the oracle. Gemini audio input costs $0.005/min.

**Deterministic validation layer (free, do first).** DNI mod-23 letter, NIE prefix mapping, 9-digit Spanish mobile/landline starting 6, 7, 8 or 9, email regex plus a domain allowlist (gmail.com, hotmail.com, outlook.com, yahoo.es, icloud.com, protonmail.com). Date of birth: valid calendar date, age 0-110. A failed check triggers a targeted re-ask of that field only.

**Number and letter normalisation.** Spanish callers mix "seis" and "6", "catorce" and "uno cuatro". Normalise both forms before validation. The `text2num` library parses Spanish number words (Catalan support UNVERIFIED). Handle "doble ocho", "dos veces cinco", "y" inside dates, and Catalan "vuit", "nou", "onze". Handle spelled letters: "be", "uve", "uve doble", "i griega", "ce", "zeta", "eñe" plus "de Barcelona" style disambiguation.

**Endpointing for the difficult caller.** pipecat mode (`vad_force_turn_endpoint=True`) finalizes on Silero stop. Soniox mode (`vad_force_turn_endpoint=False`) uses semantic endpointing with `max_endpoint_delay_ms` 500-3000, `endpoint_sensitivity` -1..1 and `endpoint_latency_adjustment_level` 0-3 (v5 only). Dictation of a DNI has natural pauses between digit groups; raise the delay during entity capture and lower it for yes/no confirmations. Both AssemblyAI (`end_of_turn_confidence_threshold`, `min_turn_silence`, `max_turn_silence`) and Flux (`eot_threshold`, `eager_eot_threshold`, `eot_timeout_ms`) expose the same idea.

**Mid-session vocabulary updates.** AssemblyAI `UpdateConfiguration` and Deepgram Flux `Configure` accept new keyterms mid-stream. Soniox sets context once at connection. If you stay on Soniox, load all stage vocabularies at start; the 8k-token cap leaves room.

## Read-back and confirmation patterns

Sources: Vapi prompting guide (https://docs.vapi.ai/prompting-guide), call-centre verification guides, Hamming AI guide.

1. One field per turn. Collect, confirm, move on. Never ask name, birth date and phone in one question.
2. Confirm each entity immediately with a closed yes/no question. Batch-confirm everything once at the end. On a correction, re-confirm only that field.
3. Read numbers in groups the TTS can say cleanly. Phone: "seis dos uno, tres cuatro cinco, seis siete ocho". DNI: four digits, four digits, then the letter. Email: local part spelled, then "arroba", domain, "punto", TLD.
4. Spell names and email local parts letter by letter. On a second mishear, switch to word anchors: "be de Barcelona, a de Alicante". Spanish call centres use city names, not NATO.
5. Use what you already know. Caller ID: "Le llamo desde el seis dos uno...? Es este su número de contacto?". A "yes" avoids a nine-digit dictation.
6. Offer an alternate channel for email. Send an SMS with a link, or ask the caller to read back a 4-digit code. Vonage and Microsoft Entra describe OTP read-back as the strong, cheap option.
7. On silence of 8 s, re-prompt once with the last question shortened, then offer a callback. Do not hang up.
8. On a mid-sentence correction ("no, no, seis, no tres"), keep the last stated value. Prompt the LLM: "the latest digit wins; ask if two candidates remain".
9. Say the check letter yourself when the digits validate: "Entonces su DNI termina en la letra T, correcto?". A wrong letter reveals a digit error before you commit.

## Recommendation

**Keep Soniox stt-rt-v5 as primary.** Reasons: native es + ca with language ID (Deepgram Flux and Nova-3 multi lack Catalan), 260 ms median TTFS with a tight 313 ms P99, 8 kHz mu-law accepted, alphanumeric focus in v5, and $0.12/hr with formatting bundled. No other vendor combines Catalan, code-switching, and low cost.

**Change these settings now.**

1. `language_hints_strict=False`, `enable_language_identification=True`. Log the per-token language to detect switches. Editor's note: keep the hint order `en, es, ca` that `turns.py` already uses; 69 of 73 public cases are English (`docs/rules.md`).
2. Rebuild `SonioxContextObject`. `general`: domain "clínica, agenda de citas", task "el paciente dicta DNI/NIE, teléfono, email, fecha de nacimiento", format "números como cifras, emails en minúscula con @". `terms`: clinic and doctor names, services, "arroba", "punto", "guion", "guion bajo", email domains, Spanish and Catalan letter names, month names. Keep under 8k tokens.
3. Decide endpointing per state. Test `vad_force_turn_endpoint=False` with `max_endpoint_delay_ms=1500` and `endpoint_sensitivity=-0.3` for dictation states. Keep pipecat VAD mode for the rest if the bench shows better barge-in.
4. Keep the pipeline at 16 kHz. Do not pass `audio_in_sample_rate=8000`. Let the Twilio serializer resample.
5. Trial `KoalaFilter` or `KrispVivaFilter` on the 5 dB clips only. Ship it only if entity CER drops.

**Add these layers.**

1. Deterministic validators for DNI, NIE, phone, email, date. Wire failed checks to a targeted re-ask. This is the highest-value hour of work.
2. Read-back protocol in the system prompt (section above).
3. Second opinion on entity turns. Live option: a parallel `AssemblyAISTTService(speech_model="universal-3-5-pro", language_codes=[ES, CA, EN], keyterms_prompt=[...])` stream ($50 free credit covers the hackathon). Batch option: buffered WAV to Scribe v2 on fal or gemini-3.5-transcribe via Vercel. Use disagreement as a "please repeat" trigger.
4. Fallback STT for outages: `DeepgramFluxSTTService` `flux-general-multi` via Cloudflare Workers AI ($100 credit). It covers es/en only; route Catalan callers to AssemblyAI instead.
5. A 50-clip private bench: 10 clean, 10 street, 10 TV, 10 kitchen, 10 car, each with one DNI, one phone, one email, mixed es/ca. Mix noise at 5 dB SNR. Score entity character error rate, not WER. Reuse the pipecat stt-benchmark harness.

**Switch primary only if** the bench shows Soniox entity CER clearly above AssemblyAI U3.5/3.6 Pro. AssemblyAI then wins on Catalan plus native code-switching, keyterms included, and the best pipecat benchmark score. Cost rises to $0.45/hr, which does not matter for the event.

## Sources

- https://soniox.com/docs/stt/models — stt-rt-v5 released 2026-06-16; v4 removed 2026-06-30; language ID and context improvements.
- https://soniox.com/blog/soniox-v5-real-time — v5 announcement; alphanumeric, telephony and noise claims; no numbers.
- https://soniox.com/pricing — $0.12/hr real-time; language ID and formatting bundled.
- https://soniox.com/docs/stt/concepts/context — context sections, 8,000-token cap, guidance.
- https://soniox.com/docs/api-reference/stt/websocket-api — language_hints_strict, endpoint params, 300-minute stream cap.
- https://soniox.com/docs/stt/rt/real-time-transcription — raw PCM config, finalize message, token model.
- https://soniox.com/docs/stt/concepts/supported-languages — Catalan `ca` and Spanish `es` supported.
- https://soniox.com/benchmarks — Soniox's view of the pipecat benchmark (August 2026 run).
- https://soniox.com/compare-stt — vendor 60-language YouTube study, English numbers only.
- https://docs.pipecat.ai/api-reference/server/services/stt/soniox — SonioxSTTService settings, VAD modes, deprecated params.
- https://github.com/pipecat-ai/stt-benchmark — full results table, semantic WER method.
- https://www.daily.co/blog/benchmarking-stt-for-voice-agents/ — benchmark write-up, 2026-02-13, English only.
- https://artificialanalysis.ai/speech-to-text — AA-WER v2 method, non-streaming top five.
- https://developers.deepgram.com/docs/models-languages-overview — Flux vs Nova-3 languages; Catalan only in Nova-3/Nova-2.
- https://developers.deepgram.com/docs/flux — Flux models, eot params, keyterms, language_hint.
- https://developers.deepgram.com/docs/keyterm — 100 terms, 500 tokens, Flux dynamic updates.
- https://deepgram.com/pricing — Nova-3, Flux and keyterm streaming rates, $200 credit.
- https://deepgram.com/learn/deepgram-launches-flux-multilingual-press-release — Flux Multilingual GA 2026-04-29, 10 languages, EOT under 400 ms.
- https://github.com/orgs/deepgram/discussions/1605 — Spanish number misrecognition on Nova-3 multi, unanswered.
- https://deepgram.com/learn/speech-to-text-benchmarks — Deepgram's own benchmark page; no alphanumeric method shown.
- https://www.assemblyai.com/docs/streaming/multilingual-transcription — U3.5 Pro 19 languages incl. Catalan, mid-sentence code-switching.
- https://www.assemblyai.com/docs/streaming/prompting-and-keyterms — keyterm limits, prompting gains, best practices.
- https://www.assemblyai.com/pricing — $0.45/hr U3.5 Pro, $0.15/hr streaming multilingual, $50 credit.
- https://docs.pipecat.ai/api-reference/server/services/stt/assemblyai — AssemblyAISTTService params and models.
- https://github.com/coval-ai/benchmarks/issues/662 — universal-3-6-pro WER gain, rate unpublished.
- https://elevenlabs.io/docs/overview/capabilities/speech-to-text — Scribe v2 languages, Catalan and Spanish in top tier, keyterm limits.
- https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime — ulaw_8000, commit strategies, VAD params.
- https://elevenlabs.io/blog/introducing-scribe-v2 — Scribe v2 release 2026-01-09.
- https://elevenlabs.io/realtime-speech-to-text — ~150 ms, $0.28-0.39/hr, mu-law accepted.
- https://docs.pipecat.ai/api-reference/server/services/stt/elevenlabs — ElevenLabsRealtimeSTTService.
- https://docs.speechmatics.com/speech-to-text/languages — Catalan real-time; bilingual packs; Melia 1 batch-only.
- https://docs.speechmatics.com/speech-to-text/features/custom-dictionary — dictionary limits, sounds_like, real-time caching.
- https://www.speechmatics.com/pricing — $100 credit; hourly rates reported by third parties only.
- https://docs.pipecat.ai/api-reference/server/services/stt/speechmatics — linden-1, additional_vocab, 16 kHz default.
- https://github.com/pipecat-ai/pipecat/issues/5717 — Speechmatics rejects 8 kHz sessions in pipecat 1.10.0.
- https://github.com/pipecat-ai/pipecat/issues/3844 — Smart Turn v3 breaks at 8 kHz input.
- https://reference-server.pipecat.ai/en/latest/api/pipecat.serializers.twilio.html — serializer resamples 8 kHz mu-law.
- https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.filters.html — Krisp, Koala, RNNoise, noisereduce filters.
- https://docs.pipecat.ai/server/services/supported-services — STT vendor list and pip extras.
- https://www.gladia.io/blog/code-switching-language-coverage-limitations — 2026-04-10; vendor code-switch comparison; Catalan-Spanish CS 51-63% WER cited.
- https://www.gladia.io/blog/solaria-3-speech-to-text-model-for-european-languages — Solaria-3 2026-06-10; vendor WER claims.
- https://www.gladia.io/pricing — $0.75/hr Starter, $0.25/hr Growth, 50 EUR credit.
- https://docs.pipecat.ai/api-reference/server/services/stt/gladia — GladiaSTTService, code_switching, mulaw.
- https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3 — Chirp 3 streaming, es and ca, auto language, 1000 phrases.
- https://docs.cloud.google.com/speech-to-text/docs/class-tokens — es-ES class tokens; ca-ES absent.
- https://docs.cloud.google.com/speech-to-text/docs/adaptation-model — phrase sets, boost, custom classes.
- https://ai.google.dev/gemini-api/docs/live-api/live-transcribe — gemini-3.5-transcribe-live, 16 kHz, 1000 vocab terms, 10-min cap.
- https://blog.google/innovation-and-ai/technology/developers-tools/build-real-time-voice-applications-gemini-audio/ — 2026-09-15; 3.5 Transcribe 4.0%/2.6% WER; 3.8 Live pricing.
- https://docs.pipecat.ai/api-reference/server/services/stt/google — GoogleSTTService and GeminiSTTService.
- https://developers.openai.com/api/docs/guides/realtime-transcription — gpt-live-transcribe, languages, prompt.
- https://developers.openai.com/api/docs/models/gpt-transcribe — $0.0045/min, language hints.
- https://github.com/openai/openai-realtime-api-beta/issues/8 — g711_ulaw 8 kHz accepted by Realtime API.
- https://docs.cartesia.ai/build-with-cartesia/stt-models/latest — ink-2 English only; ink-preview adds Spanish 2026-09-04.
- https://docs.cartesia.ai/pricing — 3 credits/s ink-2, 1 credit/s ink-whisper.
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification — continuous LID, no intra-sentence switch.
- https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ — 5 free hours; rates hidden without region.
- https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html — ca-ES and es-ES streaming, custom vocabulary support.
- https://aws.amazon.com/transcribe/pricing/ — streaming rate reported as $0.01/min (UNVERIFIED).
- https://mistral.ai/news/voxtral-transcribe-2/ — 2026-02-04; Voxtral Realtime $0.006/min; 13 languages.
- https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b — 40 locales, no Catalan, Spanish 4.11% WER.
- https://perspectives.nvidia.com/nemotron-speech/task/faq/what-are-the-most-production-ready-open-speech-recognition-models-for-european-l/ — Parakeet v3 25 languages, 6.34% WER.
- https://kyutai.org/stt/ — Kyutai STT en/fr only.
- https://huggingface.co/blog/open-asr-leaderboard — multilingual track, five languages, 2025-11-21.
- https://huggingface.co/blog/ServiceNow-AI/code-switching — 2026-06-09 code-switch benchmark, Scribe v2 first.
- https://arxiv.org/abs/2507.13875 — Catalan-Spanish code-switching ASR, Interspeech 2025.
- https://arxiv.org/abs/2506.05400 — Auto Review: second-stage error detection on phone calls.
- https://www.coval.ai/blog/best-speech-to-text-providers-in-2026-independent-benchmarks-and-how-to-choose/ — 2026-06-04 aggregate of vendor claims.
- https://docs.vapi.ai/prompting-guide — one field at a time, spell-back, caller ID, batch confirmation.
- https://developers.cloudflare.com/workers-ai/models/nova-3/ — Nova-3 on Workers AI, $0.0092/min WebSocket.
- https://developers.cloudflare.com/changelog/post/2025-10-02-deepgram-flux/ — Flux on Workers AI, WebSocket only.
- https://fal.ai/models/fal-ai/elevenlabs/speech-to-text/scribe-v2 — Scribe v2 batch on fal.
- https://vercel.com/docs/ai-gateway/modalities/speech-to-text — gemini-3.5-transcribe and gpt-4o-transcribe via AI Gateway (beta).
- https://www.sinologic.net/en/2026-05/vosk-vs-whisper-local-the-ultimate-2026-guide-to-self-hosted-speech-recognition-stt.html — whisper-streaming/WhisperLive 1-2 s latency.
