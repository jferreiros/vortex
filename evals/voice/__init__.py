"""Layer 3: the voice providers, side by side.

The same utterances go through every stack (STT -> LLM -> TTS). Measured:

- latency per stage and end to end (what the caller waits before we speak)
- transcription quality (WER) per language, clean and at 5 dB SNR
- cost per call and per 68-call Run All, from evals/voice/pricing.yaml

This layer spends real money with ``--real``. It never runs on a PR.
"""
