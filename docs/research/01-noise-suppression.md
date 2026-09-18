# Research 01 — Noise suppression before STT for 8 kHz telephony (Pipecat, Soniox)

Date: 2026-09-19. Scope: HackSpain 2026 Prosper track, "Noise" (weight 3) and "The Real Call" (weight 5).
Pipeline: Twilio Media Streams (8 kHz mu-law, 20 ms) -> Pipecat 1.11 -> Silero VAD -> Soniox stt-rt-v5.

## Summary

- Pipecat 1.11 ships five input filters: `AICFilter`, `KrispVivaFilter`, `KoalaFilter`, `RNNoiseFilter`, `NoisereduceFilter` (deprecated). All plug into `TransportParams.audio_in_filter` and run before Silero VAD.
- The only vendor with a native 8 kHz real-time model, self-serve keys and a free trial is ai-coustics (`quail-ms-l-8khz`, 30 ms latency, CPU). Krisp VIVA has the best published WER numbers but keys are application-gated.
- Evidence cuts both ways. Deepgram and a Dec 2025 paper say generic denoisers (MetricGAN+, spectral subtraction) raise WER on modern ASR in all tested conditions. Krisp and ai-coustics publish 30-46% WER reductions with their ASR-tuned models. LiveKit's own table shows both wins and losses.
- Rule for the team: measure WER on your own 5 dB SNR mixtures with the filter on and off. Ship the filter only if WER drops. Soniox v5 already claims noise and telephony robustness.
- Bandwidth extension (AudioSR, VoiceFixer, Resemble Enhance) is batch, GPU-heavy, and gives modest or negative ASR gains. Skip it for a hackathon.

## Tool table

| Name | What it does | Real-time? | Sample rate | Cost | Python | Source URL |
|---|---|---|---|---|---|---|
| Pipecat `AICFilter` (ai-coustics Quail) | Neural speech enhancement, ASR-tuned "Multi Speaker" and "Voice Focus" variants | Yes, 30 ms algorithmic | Native 8 kHz (`quail-ms-l-8khz`, `quail-ms-s-8khz`), 16 kHz; SDK resamples 8-192 kHz | Free trial (30 days, UNVERIFIED exact terms); Startup $135-149/mo for 100k min | `pip install "pipecat-ai[aic]"`, `aic-sdk` | https://docs.pipecat.ai/server/utilities/audio/aic-filter |
| Pipecat `KrispVivaFilter` (Krisp VIVA) | Voice isolation: removes noise and competing voices; telephony models `krisp-viva-vi-tel-*` | Yes, 15 ms algorithmic (VI 2.5) | 8-48 kHz (VAD documented); telephony models target 8-16 kHz | Application-gated trial; enterprise/startup quotes; no public price | Platform wheel `krisp_audio` from Krisp portal | https://docs.pipecat.ai/pipecat/features/krisp-viva |
| Pipecat `KoalaFilter` (Picovoice Koala) | On-device DNN noise suppression | Yes, frame-based, small delay (`delay_sample`) | Fixed `koala.sample_rate` (16 kHz per Picovoice docs, UNVERIFIED in this fetch) | Free plan: 3 active users/month; commercial Foundation plan | `pip install "pipecat-ai[koala]"`, `pvkoala` 3.0.1 | https://docs.pipecat.ai/server/utilities/audio/koala-filter |
| Pipecat `RNNoiseFilter` (RNNoise) | Classic GRU noise suppressor, 480-sample frames | Yes, ~10 ms frames | 48 kHz only; Pipecat resamples with SOXR "QQ" | Free, BSD | `pip install "pipecat-ai[rnnoise]"` (uses `pyrnnoise`) | https://reference-server.pipecat.ai/en/latest/_modules/pipecat/audio/filters/rnnoise_filter.html |
| Pipecat `NoisereduceFilter` | Spectral gating (`noisereduce` lib) | Yes but deprecated; Pipecat says use Krisp/AIC | Any | Free | `noisereduce` | https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.filters.noisereduce_filter.html |
| DeepFilterNet3 | Deep-filtering full-band enhancement, MIT/Apache | Yes with streaming wrappers; ~30-50 ms | 48 kHz native; wrappers resample from 8 kHz | Free | `pip install deepfilternet` (batch); `pipecat-deepfilternet-stream` (`DeepFilterNetStreamFilter`); `dfnstream-py` | https://github.com/Rikorose/DeepFilterNet |
| DeepFilterNet3 on fal.ai | Batch file denoise + upsample to 48 kHz | No, file upload | Output 48 kHz | $0.001/s of audio | HTTP/`fal-client` | https://fal.ai/models/fal-ai/deepfilternet3 |
| Meta `denoiser` (Demucs) | Causal waveform enhancer, 16 ms per 40 ms frame on laptop CPU | Yes, ~40 ms+ | 16 kHz | Free, MIT (research 2020) | `pip install denoiser` | https://github.com/facebookresearch/denoiser |
| Silero denoise | `silero_denoise` models (`small_fast`, `large_fast`, `small_slow`) | Batch-oriented, UNVERIFIED streaming | UNVERIFIED | Free but AGPL-3.0 (source disclosure for commercial use) | `silero` via torch.hub | https://github.com/snakers4/silero-models |
| SpeechBrain MetricGAN+ / SepFormer | Research enhancers, VoiceBank / WHAM! | Batch; not causal | 16 kHz | Free | `speechbrain` | https://huggingface.co/speechbrain/sepformer-wham16k-enhancement |
| NVIDIA Maxine AFX SDK | GPU denoise + dereverb for narrow/wide/ultra-wideband | Yes | 8/16/48 kHz | Free SDK, needs NVIDIA GPU; C API | C SDK, no official Python | https://docs.nvidia.com/maxine/afx/latest/index.html |
| ElevenLabs Audio Isolation | Voice isolation, removes music/noise | No, whole file per HTTP call (chunked response only) | Input `pcm_s16le_16` (16 kHz) | $0.12/min | REST; also on fal.ai | https://elevenlabs.io/docs/api-reference/audio-isolation/stream |
| Resemble Enhance | Diffusion denoise + super-resolution | No, batch GPU | 44.1 kHz out | Free, open source | `resemble-enhance` | https://www.resemble.ai/introducing-resemble-enhance/ |
| AudioSR / VoiceFixer | Diffusion / GAN bandwidth extension to 48 kHz | No, batch GPU | 2-16 kHz in, 48 kHz out | Free | `audiosr`, `voicefixer` | https://audioldm.github.io/audiosr/ |
| Adobe Podcast Enhance | Studio-quality cleanup | No; no public API as of 2026 | n/a | Web app | None | https://cleanvoice.ai/blog/adobe-podcast-api-review/ |
| Auphonic / Cleanvoice / Dolby.io | Post-production APIs | No, batch | n/a | Paid per hour | REST | https://mixinggpt.com/blog/best-ai-audio-cleanup-tools-2026 |
| Google STT `denoiser_audio` (Chirp 3) | Built-in denoiser inside Google STT; cannot remove voices | Inside STT request | Google side | STT price | Google client | https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3 |
| LiveKit Cloud enhanced NC | Krisp NC/VIVA and ai-coustics Quail applied in LiveKit Cloud | Yes | Telephony variant exists | LiveKit Cloud only | LiveKit agents | https://docs.livekit.io/transport/media/noise-cancellation/ |
| Cloudflare Workers AI | STT/TTS (Deepgram Nova-3, Aura, Flux), smart-turn | n/a | n/a | Hackathon credits | REST | https://developers.cloudflare.com/workers-ai/models/ |

No dedicated denoise model appears in the Cloudflare Workers AI catalog. Vercel AI Gateway routes LLMs only (UNVERIFIED for audio).

## Detailed notes per tool

### Pipecat filters (pipecat.audio.filters, 1.11)

- Interface: `BaseAudioFilter` with `start(sample_rate)`, `stop()`, `process_frame(FilterControlFrame)`, `filter(audio: bytes) -> bytes`.
- Attach with `TransportParams(audio_in_filter=...)`. `FastAPIWebsocketParams` inherits this field. The filter runs before VAD.
- `AICFilter(license_key, model_id, model_path, model_download_dir, enhancement_level)`. Env var `AIC_SDK_LICENSE`. Models download from artifacts.ai-coustics.io on first use. Int16 PCM in, float32 inside. The docs list `quail-l-8khz`; the ai-coustics quickstart lists `quail-ms-l-8khz`.
- `KrispVivaFilter(model_path, frame_duration=10, noise_suppression_level=100.0, api_key, tts_model_path, ...)`. Env vars `KRISP_VIVA_API_KEY`, `KRISP_VIVA_FILTER_MODEL_PATH`. Needs `krisp_audio` wheel (e.g. `krisp_audio-1.8.0-cp312-...whl`) and `.kef` model files such as `krisp-viva-vi-tel-v2.kef`.
- `KoalaFilter(access_key)`. Env var `KOALA_ACCESS_KEY`. Sample rate must equal `koala.sample_rate`. Whether Pipecat resamples 8 kHz for Koala is UNVERIFIED.
- `RNNoiseFilter(resampler_quality="QQ")`. Resamples any input to 48 kHz and back with SOXR stream resamplers. Buffers to 480-sample frames.
- `NoisereduceFilter`: deprecated. `KrispFilter` (old Krisp SDK) is deprecated in favour of `KrispVivaFilter`.
- Pipecat 1.11.0 added `BaseAudioResampler.flush()`/`reset()`. Useful if you write a custom resampling filter.

### ai-coustics (aic-sdk, Quail)

- Native SDK (C core, Python/Node/Rust bindings), CPU only, 30 ms latency for every Quail model.
- Models with native 8 kHz: Quail Multi Speaker L (33-35 MB) and S (8-9 MB). Voice Focus 2.2 is 16 kHz only. Rook (human-listening) has 8/16/48 kHz.
- "Quail Multi Speaker" is the ASR-oriented variant (claims up to 30% WER reduction). "Voice Focus" isolates the primary speaker (claims up to 43% relative WER reduction across ASR providers).
- SDK resamples internally for 8-192 kHz. Docs recommend the native-rate model when it exists.
- License key from developers.ai-coustics.com. Env `AIC_SDK_LICENSE`. Free trial: reviews say 30 days, no card (UNVERIFIED on the pricing page). Plans: Startup $135/mo annual or $149/mo, 100k minutes.
- Developer platform launched 16 Sep 2025 (Berlin company, not US).
- Python: `pip install aic-sdk`; `aic.Model.download("quail-ms-l-8khz", "./models")`, `ProcessorConfig.optimal(model)`, `Processor.process(block)`.

### Krisp VIVA (Krisp, Berkeley CA)

- VIVA SDK launched July 2025. VIVA 2.0 on 6 May 2026 added Turn Prediction v3, Interrupt Prediction v1, TTS/accent/gender detectors, Voice Isolation v3. All run on server CPUs.
- Voice Isolation 2.5 (12 Aug 2026): 15 ms latency, CPU only. Claims 46.4% average WER reduction (15.35% to 8.22%) across 10 STT systems incl. Soniox, Deepgram, Google, ElevenLabs. Competing speakers: 35.9% to 10.9%. Clean audio penalty near zero (2.15% vs 2.10%).
- Telephony: `krisp-viva-vi-tel-v2.1` targets 8-16 kHz, G.711/G.722. `krisp-viva-tel-lite-v1` (Nov 2025) is 3.5x smaller, 15 ms.
- Access: "tell us your use case" form, trial after approval. Risky for a 1-2 day hackathon.
- Python SDK is a platform wheel, not on PyPI.

### DeepFilterNet3

- 48 kHz only in the official package. Algorithmic latency about 40 ms (20 ms windows, 2-frame lookahead). Rust core, Python wrappers, LADSPA plugin for PipeWire.
- Streaming Python paths: `pipecat-deepfilternet-stream` (`DeepFilterNetStreamFilter`, SOXR resampling from 8 kHz Twilio mu-law, 30-50 ms delay, RTF 0.10-0.13 on Apple Silicon) and `dfnstream-py` (ONNX Runtime, MIT). Both are third-party and small; verify they still install.
- For 8 kHz input, the model sees only 0-4 kHz of a 48 kHz frame. It still works but wastes compute. ASR benefit is UNVERIFIED.
- fal.ai hosts DeepFilterNet3 as a batch endpoint at $0.001 per second of audio. Good for offline experiments, not for the live call.

### RNNoise

- 48 kHz, 480-sample frames, GRU, very cheap. Reputation: fine on stationary noise, weaker on non-stationary noise and at low SNR; DeepFilterNet3 generalises better in comparisons. Twilio ships RNNoise as its open-source client-side option.

### Koala (Picovoice, Vancouver)

- On-device DNN, Apache-licensed SDK, AccessKey from Picovoice Console. Free plan allows 3 active users/month and works for demos. Benchmarked on DNS Challenge data by STOI; no WER numbers.

### Meta denoiser (Demucs, 2020)

- Causal, 16 kHz, 16 ms compute per 40 ms frame on a laptop CPU. Needs PyTorch. Old model; no telephony tuning.

### Silero denoise, SpeechBrain, Resemble Enhance, VoiceFixer, AudioSR

- Research or batch tools. AGPL (Silero), non-causal (SepFormer, MetricGAN+), diffusion GPU (Resemble Enhance, AudioSR). Not for a 20 ms real-time loop.

### NVIDIA Maxine AFX

- Real-time denoise and dereverb, narrowband supported, but needs an NVIDIA GPU and a C SDK. No fit for the team's stack.

### Hosted batch services

- ElevenLabs Audio Isolation: HTTP file in, chunked audio out, $0.12/min. Also on fal.ai. Not streaming input.
- Adobe Podcast Enhance: no public API. Auphonic, Cleanvoice, Dolby.io: batch post-production.

### STT-side options

- Google STT v2 has `denoiser_config.denoise_audio` (removes music, rain, traffic; not voices). Team uses Soniox, so not applicable.
- Soniox v5 (16 Jun 2026): "better robustness on noisy audio, telephony, far-field, accents, overlapping speech". Accepts `pcm_mulaw` at 8000 Hz. Context/terms improve names and digits. No preprocessing guidance found.
- Deepgram Nova-3 markets noise robustness and explicitly tells users not to denoise.

## Bandwidth extension (8 kHz -> wideband)

- AudioSR, NVSR, VoiceFixer, Resemble Enhance, CogSR are diffusion/GAN batch models on GPU. Latency is seconds per clip.
- Academic gains for ASR are modest (a mixed-bandwidth GAN framework reports +3.65% accuracy on narrowband). Some super-resolution models raise WER (AudioSR 12.15% WER vs CogSR 4.20% on 4 kHz inputs, per CogSR paper).
- Soniox and other telephony-trained STT already model 8 kHz speech. Verdict: waste of time for this hackathon.

## Evidence on denoise-before-STT

Against pre-filtering:
- Deepgram, "The Noise Reduction Paradox": denoisers strip acoustic detail that end-to-end models use; enterprise customers report lower accuracy after high-end suppression. Exception they admit: turn-taking and VAD false triggers in noise.
- Deepgram docs, "Audio Preprocessing & Barge-In": "Always test without preprocessing first." "Only add preprocessing if you can measure a clear improvement on your own audio."
- Deepgram, "Noise-Robust Speech Recognition": spectral subtraction can add 8 dB SNR and still raise WER 15%; WER doubles from 15 dB to 5 dB SNR.
- arXiv 2512.17562 (Dec 2025), "When De-noising Hurts": MetricGAN+ enhancement raised semantic WER in all 40 configurations (Whisper, Parakeet, Gemini Flash 2.0, Parrotlet), by 1.1 to 46.6 points.
- arXiv 2406.12699 (Jun 2024), "Bridging the Gap": independently trained SE models add artifacts and harm ASR; a bridge module is needed.

For pre-filtering (vendor claims, ASR-tuned models):
- Krisp VI 2.5: 46.4% average WER reduction across 10 STT systems incl. Soniox; near-zero penalty on clean audio.
- ai-coustics Quail: up to 43% relative WER reduction (Voice Focus), up to 30% (Multi Speaker).
- LiveKit docs table (Deepgram Nova 3, gym sample): original 117.6% WER, ai-coustics VF 2.1 S 7.1%, Krisp VIVA 11.8%, ai-coustics VF 2.1 L 14.3%. Same vendor, two model sizes, opposite ranking. This shows the effect is sample-dependent.
- LiveKit community thread reports audio degradation after enabling BVC. Anecdotal.

Reading: generic enhancers (spectral gating, MetricGAN+, likely RNNoise) hurt modern ASR. Products trained for ASR (Krisp VIVA, ai-coustics Quail Multi Speaker) can help, mainly with competing voices and non-stationary noise. The "Noise" problem is TV/street/car at 5 dB. The "Real Call" is a kitchen with a grandmother, likely with other voices. A voice-isolation model fits the second case better than the first. Only measurement decides.

Second benefit independent of WER: a filter before Silero VAD cuts false speech starts and false interruptions. Deepgram concedes this. Keep VAD threshold tuning as the cheap alternative.

## Recommended plan for the team (1-2 days)

Order of attempts. Stop when a step wins.

1. Build the yardstick first. Take 5-10 problem-1 recordings, mix noise at 5 dB SNR (same as the scorer), run Soniox stt-rt-v5 on raw vs filtered audio. Compute WER, and a stricter "name and DNI digits correct" rate. Do not ship a filter that does not lower both. (30-60 min with `jiwer`.)
2. Baseline without filters. Give Soniox `context` with the clinic's names, "DNI", and digit patterns. Soniox says context helps most in noisy audio. Check if this alone clears the bar.
3. `AICFilter` with `model_id="quail-ms-l-8khz"` (ASR variant, native 8 kHz). Sign up at developers.ai-coustics.com, set `AIC_SDK_LICENSE`, `pip install "pipecat-ai[aic]"`. 30 ms added latency. Try `enhancement_level` 0.5-1.0. Also try `quail-vf-2.2-l-16khz` for the grandmother call if other voices are the problem.
4. `RNNoiseFilter` as the zero-signup fallback. `pip install "pipecat-ai[rnnoise]"`. Expect small or negative WER change; keep only if VAD stability improves.
5. Optional: `KoalaFilter` (free Picovoice key) or `pipecat-deepfilternet-stream`. Only if steps 3-4 fail and time remains.
6. Krisp VIVA: request access now in parallel; use only if keys arrive. Best published numbers, worst access.
7. Skip bandwidth extension, batch APIs (ElevenLabs isolation, fal DeepFilterNet3), Maxine, Silero, SpeechBrain.
8. In parallel, harden the dialogue: always read back name and DNI digit by digit and ask for confirmation. This wins points no filter can.

Attach a built-in filter:

```python
from pipecat.audio.filters.aic_filter import AICFilter

params = FastAPIWebsocketParams(
    audio_in_enabled=True,
    audio_out_enabled=True,
    audio_in_filter=AICFilter(
        license_key=os.environ["AIC_SDK_LICENSE"], model_id="quail-ms-l-8khz"
    ),
    vad_analyzer=SileroVADAnalyzer(),
    serializer=TwilioFrameSerializer(stream_sid),
)
```

Custom frame filter sketch (any denoiser that needs 16 or 48 kHz, input 8 kHz):

```python
import numpy as np
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.audio.resamplers.soxr_stream_resampler import SOXRStreamAudioResampler


class DenoiseFilter(BaseAudioFilter):
    def __init__(self, denoise, model_rate=16000):  # denoise: float32 -> float32 block fn
        self._fn, self._mr, self._up, self._down = denoise, model_rate, None, None

    async def start(self, sample_rate: int):
        self._sr = sample_rate
        self._up = SOXRStreamAudioResampler()
        self._down = SOXRStreamAudioResampler()

    async def stop(self):
        pass

    async def process_frame(self, frame):
        pass

    async def filter(self, audio: bytes) -> bytes:
        pcm = await self._up.resample(audio, self._sr, self._mr)
        x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        y = np.clip(self._fn(x), -1, 1)
        return await self._down.resample((y * 32767).astype(np.int16).tobytes(), self._mr, self._sr)
```

Check the resampler class name and `resample()` signature against Pipecat 1.11 before use (UNVERIFIED here). Keep the denoiser stateful across calls; Twilio delivers 160 samples per 20 ms.

## Sources

- https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.filters.html — filter module list (AIC, Base, Koala, KrispViva, RNNoise).
- https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.filters.aic_filter.html — AICFilter constructor params.
- https://docs.pipecat.ai/server/utilities/audio/aic-filter — install extra `pipecat-ai[aic]`, env `AIC_SDK_LICENSE`, model IDs incl. 8 kHz.
- https://reference-server.pipecat.ai/en/latest/_modules/pipecat/audio/filters/krisp_viva_filter.html — KrispVivaFilter source, env vars, `.kef` models.
- https://docs.pipecat.ai/pipecat/features/krisp-viva — Krisp wheel install, model file names, sample rates.
- https://github.com/pipecat-ai/pipecat/blob/main/examples/voice/voice-krisp-viva.py — `audio_in_filter=KrispVivaFilter()` for Twilio transport.
- https://reference-server.pipecat.ai/en/latest/_modules/pipecat/audio/filters/rnnoise_filter.html — RNNoiseFilter resamples to 48 kHz, `pipecat-ai[rnnoise]`.
- https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.filters.noisereduce_filter.html — NoisereduceFilter deprecated.
- https://docs.pipecat.ai/server/utilities/audio/koala-filter — KoalaFilter install and env var.
- https://reference-server.pipecat.ai/en/latest/_modules/pipecat/audio/filters/base_audio_filter.html — BaseAudioFilter interface.
- https://reference-server.pipecat.ai/en/latest/api/pipecat.transports.base_transport.html — `TransportParams.audio_in_filter`.
- https://github.com/pipecat-ai/pipecat/releases/tag/v1.11.0 — 1.11.0 resampler flush/reset.
- https://ai-coustics.com/quail — Quail claims: 30 ms, no GPU, up to 43% WER reduction.
- https://github.com/ai-coustics/aic-sdk-py — `pip install aic-sdk`, code example, license.
- https://docs.ai-coustics.com/tutorials/sdk-quickstart — model IDs `quail-ms-l-8khz`, `quail-vf-2.2-l-16khz`.
- https://docs.ai-coustics.com/reference/sdk/models — model table with native rates, sizes, 30 ms latency, resampling 8-192 kHz.
- https://ai-coustics.com/pricing — Startup $135/mo annual, 100k minutes.
- https://ai-coustics.com/blog/developer-platform-api-playground-sdk — developer platform launch 16 Sep 2025.
- https://www.juststeveking.com/reviews/ai-coustics-in-review/ — 30-day free trial claim (third party).
- https://finance.yahoo.com/sectors/technology/articles/krisp-launches-viva-2-0-125700659.html — VIVA 2.0, 6 May 2026.
- https://krisp.ai/blog/voice-isolation-2-5/ — VI 2.5, 12 Aug 2026, 46.4% WER reduction, 15 ms.
- https://krisp.ai/blog/small-voice-isolation-model/ — `krisp-viva-tel-lite-v1`, Nov 2025, telephony codecs.
- https://sdk-docs.krisp.ai/docs/getting-started-server — server SDK basics, 10 ms frames.
- https://krisp.ai/developers/ — access via use-case form (application-gated).
- https://github.com/Rikorose/DeepFilterNet — 48 kHz only, `pip install deepfilternet`, MIT/Apache.
- https://github.com/vahidkowsari/pipecat-deepfilternet-stream — `DeepFilterNetStreamFilter`, 8 kHz Twilio support, 30-50 ms.
- https://github.com/outspeed-ai/dfnstream-py — `dfnstream-py`, ONNX streaming, MIT.
- https://fal.ai/models/fal-ai/deepfilternet3 — batch, $0.001/s, 48 kHz out.
- https://github.com/pengzhendong/pyrnnoise — `pip install pyrnnoise`, 480-sample frames at 48 kHz.
- https://pypi.org/project/pvkoala/ — pvkoala 3.0.1 (Feb 2026), AccessKey.
- https://picovoice.ai/docs/api/koala-python/ — `sample_rate`, `frame_length`, `delay_sample`, `process()`.
- https://picovoice.ai/docs/benchmark/noise-suppression-picovoice-koala/ — STOI benchmark vs RNNoise.
- https://picovoice.ai/pricing/ — free plan limits (3 active users/month).
- https://github.com/facebookresearch/denoiser — Demucs denoiser, 16 ms per frame on CPU.
- https://github.com/snakers4/silero-models — Silero denoise models, AGPL.
- https://huggingface.co/speechbrain/sepformer-wham16k-enhancement — SepFormer 16 kHz enhancement.
- https://docs.nvidia.com/maxine/afx/latest/index.html — Maxine AFX SDK, narrowband support, GPU.
- https://elevenlabs.io/docs/api-reference/audio-isolation/stream — file-in HTTP endpoint, `pcm_s16le_16`.
- https://elevenlabs.io/pricing/api — Voice Isolator $0.12/min.
- https://www.resemble.ai/introducing-resemble-enhance/ — Resemble Enhance, batch diffusion.
- https://audioldm.github.io/audiosr/ — AudioSR bandwidth extension to 48 kHz.
- https://arxiv.org/pdf/2512.16304 — CogSR paper; WER of AudioSR/NVSR on 4 kHz inputs.
- https://dl.acm.org/doi/fullHtml/10.1145/3622896.3622923 — mixed-bandwidth ASR GAN, +3.65% on narrowband.
- https://cleanvoice.ai/blog/adobe-podcast-api-review/ — Adobe Podcast has no public API.
- https://mixinggpt.com/blog/best-ai-audio-cleanup-tools-2026 — batch cleanup tools overview.
- https://deepgram.com/learn/the-noise-reduction-paradox-why-it-may-hurt-speech-to-text-accuracy — denoise hurts ASR; VAD exception.
- https://developers.deepgram.com/guides/deep-dives/audio-preprocessing-barge-in — "test without preprocessing first".
- https://deepgram.com/learn/noise-robust-speech-recognition-methods-best-practices — spectral subtraction +8 dB SNR, +15% WER.
- https://arxiv.org/abs/2512.17562 — "When De-noising Hurts", Dec 2025, 40/40 configs worse.
- https://arxiv.org/abs/2406.12699 — "Bridging the Gap", SE artifacts harm ASR.
- https://docs.livekit.io/transport/media/noise-cancellation/ — model list and WER table (117.6% -> 7.1-14.3%).
- https://livekit.com/blog/noise-cancellation — 10 Jun 2026 post, Krisp and ai-coustics models.
- https://community.livekit.io/t/unexpected-audio-degradation-after-enabling-bvc-noise-cancellation-in-livekit-voice-agent/745 — BVC degradation report.
- https://soniox.com/blog/soniox-v5-real-time — v5 real-time, 16 Jun 2026, noise/telephony claims.
- https://soniox.com/docs/stt/models — stt-rt-v5 robustness statement, v4 retirement.
- https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3 — Google `denoiser_audio` option.
- https://www.twilio.com/en-us/changelog/twilio-voice-js-sdk-noise-cancellation-reference-components — Twilio JS SDK RNNoise/Krisp components (client-side only).
- https://developers.cloudflare.com/workers-ai/models/ — Workers AI catalog, no denoise model found.
