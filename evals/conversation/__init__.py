"""Layer 2: the conversation, as text.

A scenario is a script of what the caller says, turn by turn, with corrections,
interruptions and traps. A *brain* plays the receptionist over the real tool
registry and the fake clinic; the runner checks the actions that would have
been submitted, the path the brain took, and the transcript for leaks.

Brains:

- ``rules``   deterministic reference receptionist over the script's ``means``
              annotations. No key. Proves the harness, the tools and the
              state threading. Says nothing about the model.
- ``openai``  the real model in text mode, driven by ``says`` only. Cents per
              scenario. Records a cassette with ``--record``.
- ``replay``  the cassette from the last ``openai`` run. Deterministic. A
              prompt that changed since recording is reported *unverified*.
"""
