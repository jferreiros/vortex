"""Which tools still delegate to the contract stubs.

A case that passes against a stub proves nothing about the lane. The report
marks such passes *hollow* so a green board built on stubs never reads as done.
"""

from __future__ import annotations

import inspect
from functools import cache

from vortex import tools as registry


@cache
def stub_tools() -> frozenset[str]:
    out: set[str] = set()
    for name, spec in registry.TOOLS.items():
        try:
            source = inspect.getsource(spec.fn)
        except (OSError, TypeError):
            continue
        if "contract.stub_" in source or "stub_" + name in source:
            out.add(name)
    return frozenset(out)


def is_stub(tool: str) -> bool:
    return tool in stub_tools()
