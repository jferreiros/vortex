<!-- One or two lines: what changes and why. Link the problem_id if it targets one. -->

## Checklist (hard rules from CLAUDE.md)

- [ ] I only touched my lane's folder. Any change to `vortex/contract.py`, `vortex/tools.py` or `vortex/settings.py` was agreed on the call, and no contract signature was renamed or retyped.
- [ ] Every path through this change still ends in a submission: a refusal sends `NO_ACTION` with a typed `reason`, never nothing.
- [ ] Every `patient_id`, `appointment_id` and `appointment_type_id` comes from the clinic API, never from the caller or the model.
- [ ] Nothing is shared between sockets: no module-level session, conversation or in-flight `call_id`.
- [ ] No `.env`, API key or `logs/*.jsonl` in the diff. CI is green, or I explain below why it must merge red.
