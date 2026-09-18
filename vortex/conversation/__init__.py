"""conversation/ - the dialogue: prompt, turns, interruptions, language.

Owner: the conversation lane.

Done in the base:
- ``prompt.py``   placeholder system prompt + greeting.
- ``turns.py``    turn-taking settings and the list of tools the model sees.
- ``language.py`` language hole.

The voice pipeline (line/pipecat_voice.py) reads these three modules and
nothing else from this lane. Change behaviour here, not in line/.
"""
