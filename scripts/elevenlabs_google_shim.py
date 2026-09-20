"""ElevenLabs-compatible REST shim backed by Google Cloud TTS (Chirp3)."""
import base64, json, os
from aiohttp import web
from google.cloud import texttospeech

VOICES = {
    "es": ("es-ES", "es-ES-Chirp3-HD-Aoede"),
    "en": ("en-US", "en-US-Chirp3-HD-Aoede"),
    "ca": ("es-ES", "es-ES-Chirp3-HD-Aoede"),
    "gl": ("es-ES", "es-ES-Chirp3-HD-Aoede"),
    "eu": ("es-ES", "es-ES-Chirp3-HD-Aoede"),
}
client = texttospeech.TextToSpeechClient()

async def tts(request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    lang = (body.get("language_code") or "es").split("-")[0].lower()
    lc, name = VOICES.get(lang, VOICES["es"])
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
    # strip the 44-byte WAV header if present (LINEAR16 comes raw from API)
    if audio[:4] == b"RIFF":
        audio = audio[44:]
    line = json.dumps({"audio_base64": base64.b64encode(audio).decode()}) + "\n"
    return web.Response(status=200, text=line, content_type="application/json")

app = web.Application()
app.router.add_post("/v1/text-to-speech/{voice}/stream/with-timestamps", tts)
app.router.add_post("/v1/text-to-speech/{voice}", tts)
web.run_app(app, host="127.0.0.1", port=8799, print=None)
