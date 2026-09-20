"""ElevenLabs-compatible REST shim backed by Google Cloud TTS.

The voice path segment is the *resolved* voice name from the caller. With
per-personality voices enabled it may already be a Google voice name; older
callers may still send an opaque provider id, so a named fallback keeps the
line audible instead of guessing silently.
"""
import base64, json, os
from aiohttp import web
from google.cloud import texttospeech

DEFAULT_VOICES = {
    "es": ("es-ES", "es-ES-Chirp3-HD-Kore"),
    "en": ("en-US", "en-US-Chirp3-HD-Kore"),
    "ca": ("es-ES", "es-ES-Chirp3-HD-Kore"),
    "gl": ("es-ES", "es-ES-Chirp3-HD-Kore"),
    "eu": ("es-ES", "es-ES-Chirp3-HD-Kore"),
}
client = texttospeech.TextToSpeechClient()


def _google_voice(raw_voice, lang):
    voice = (raw_voice or "").strip()
    if voice.startswith(("es-", "en-", "ca-", "gl-", "eu-")):
        return voice.split("-Chirp3", 1)[0] if "-Chirp3" in voice else "-".join(voice.split("-")[:2]), voice
    return DEFAULT_VOICES.get(lang, DEFAULT_VOICES["es"])


async def tts(request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    lang = (body.get("language_code") or "es").split("-")[0].lower()
    lc, name = _google_voice(request.match_info.get("voice", ""), lang)
    if not text:
        return web.Response(status=200, text="\n", content_type="application/json")
    req = texttospeech.SynthesizeSpeechRequest(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code=lc, name=name),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=8000,
            speaking_rate=1.0,
        ),
    )
    audio = client.synthesize_speech(request=req).audio_content
    if audio[:4] == b"RIFF":
        audio = audio[44:]
    line = json.dumps({"audio_base64": base64.b64encode(audio).decode()}) + "\n"
    return web.Response(status=200, text=line, content_type="application/json")

app = web.Application()
app.router.add_post("/v1/text-to-speech/{voice}/stream/with-timestamps", tts)
app.router.add_post("/v1/text-to-speech/{voice}", tts)
web.run_app(app, host="127.0.0.1", port=8799, print=None)
