---
description: Take a fresh clone from install to a running local server and a practice call, step by step, checking each step.
---

Walk me through the local setup of this repo. Follow the `setup` skill in
`.claude/skills/setup/SKILL.md` exactly, in order, and check each step before
you move to the next:

1. Run `uv sync --all-groups`. Report errors.
2. If `.env` does not exist, run `cp .env.example .env`. Do not ask me for the
   API key. Say that the project works without it, against fake data, and that
   the team hands the key out on WhatsApp. Never write a key into a file yourself.
3. Run `make smoke`. If it fails, stop and show me the failure.
4. Run `make test` and `make lint`. Report the counts.
5. Start the server with `make run` in the background. Wait for
   `curl -s http://localhost:7860/health` to answer. Show me the `clinic` and
   `voice` modes it reports.
6. Run `make call N=2`. Show me the frames sent and received.
7. Stop the server you started.
8. Tell me the next manual steps: how to open the tunnel, how to build the
   `wss://<host>/ws` endpoint with the path included, where to paste it on the
   dashboard (Settings -> Integration), and how to launch a practice call from
   the Problems page. Keep it to the exact commands and fields from the skill.

Do not edit any file in `vortex/`. Do not commit anything.
