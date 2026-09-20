"""database/ — the product's own persistence layer, on Postgres.

One hosted store (Supabase), reached over PostgREST. Nothing here opens a
file or a connection: every call is a stateless HTTPS request with the
service-role key, so ten concurrent sockets share nothing at all.

Modules:

- ``remote.py``         the PostgREST client — ``select`` / ``upsert`` /
                        ``update`` / ``delete`` / ``count``, and
                        ``enabled()``, which is false when the keys are unset.
- ``models.py``         ``CallRecord`` / ``AppointmentRecord`` — plain,
                        typed rows, no ORM.
- ``db.py``             every read and write the product does, by name.
- ``hooks.py``          the glue a lane calls: turns a submitted
                        book/cancel/reschedule ``Action`` into rows.
- ``confirmations.py``  the day-before-the-appointment outbound confirmation
                        job, and the ``ConfirmationCaller`` interface the
                        line will implement for real once it can dial out.
- ``supabase/``         ``migrations/*.sql`` and ``migrate.py``, the only
                        thing in the repo that opens a real Postgres
                        connection (``SUPABASE_DB_URL``) — DDL cannot go
                        through PostgREST.
- ``seed/``             the demo's starting diary, as re-runnable SQL.
- ``scripts/``          standalone entry points (``load_seed.py``,
                        ``run_confirmations.py``).

See ``database/README.md`` for the schema, the design decisions behind it,
and how to apply a migration.
"""
