"""database/ — the product's own persistence layer.

Not a refactor of ``logs/calls.jsonl``: that log stays exactly as it is, read
by every observability view (``vortex/observability/``) and by the wall. This
is a second, purpose-built store for the two things a clinic's own system
would actually keep — appointments and the calls that touched them — queried
by id and by date, not replayed event by event.

Modules:

- ``schema.py``        versioned SQL migrations, applied in order once each.
- ``models.py``        ``CallRecord`` / ``AppointmentRecord`` — plain,
                        typed rows, no ORM.
- ``db.py``             connection handling and every read/write query.
- ``hooks.py``          the glue a lane calls: turns a submitted
                        book/cancel/reschedule ``Action`` into rows.
- ``confirmations.py``  the day-before-the-appointment outbound confirmation
                        job, and the ``ConfirmationCaller`` interface the
                        line will implement for real once it can dial out.
- ``scripts/``          standalone entry points (``run_confirmations.py``,
                        the pre-existing ``refresh_slots.py`` auxiliary cache
                        builder, unrelated to this layer).

See ``database/README.md`` for the schema, the design decisions behind it,
and what still has to be built before a real outbound call can be placed.
"""
