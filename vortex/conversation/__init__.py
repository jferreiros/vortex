"""conversation/ - the dialogue: prompt, turns, interruptions, language.

Owner: the conversation lane. Problems 11 (languages), 12 (noise),
13 (the difficult caller) and 14 (adversarial and privacy).

- ``prompt.py``       the receptionist's system prompt, the greeting and the
                      canned lines (idle nudge, emergency, refusal) per language.
- ``turns.py``        turn-taking settings, the pipecat turn strategies and the
                      list of tools the model sees.
- ``language.py``     language detection (English default), TTS voice per language.
- ``stt_context.py``  the vocabulary handed to the STT.

The voice pipeline (line/pipecat_voice.py) reads these modules and nothing
else from this lane. Change behaviour here, not in line/.
"""
