"""Schema management for the hosted Postgres store.

``migrations/`` holds the numbered SQL files; ``migrate.py`` applies them.
Nothing at runtime imports this package — the line and the board talk to the
same database through PostgREST (``database/remote.py``), never over a direct
Postgres connection. DDL is the one thing that needs the real thing.
"""
