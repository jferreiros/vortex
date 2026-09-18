"""Layer 1: the logic, without voice.

Cases enter through the tool contract and check the typed answer, or run a
short flow of tools and check the actions that would have been submitted.
No audio, no model, no network. Seconds. Runs on every pull request.
"""
