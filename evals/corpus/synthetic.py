"""Deprecated alias for ``evals.corpus.hydrate``.

uv run python -m evals.corpus.hydrate
uv run python -m evals.corpus.synthetic   # same thing
"""

from evals.corpus.hydrate import (  # noqa: F401
    SYNTHETIC_DATA_DIR,
    build,
    build_appointments,
    build_logs,
    build_manifest,
    build_patients,
    enrich_from_client,
    enrich_live,
    identities_in_case,
    main,
    spoken_appointments,
    write_pack,
)

# Older callers imported write_world / ROSTER_DIR / build_index.
write_world = write_pack
ROSTER_DIR = SYNTHETIC_DATA_DIR
build_index = build_manifest


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
