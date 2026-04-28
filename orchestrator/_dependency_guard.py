"""Startup-time check that fastmcp is installed at a runnable version.

fastmcp 2.x lacks ``fastmcp.server.tasks.routing``; fastmcp 3.x's server init
imports it transitively. A user who installs against an unpinned ``fastmcp>=2.0.0``
gets a confusing ``ModuleNotFoundError`` on the first request rather than at
import time. This guard converts that into an actionable ``SystemExit`` with a
fix command, surfaced before any tools register.
"""

from __future__ import annotations

import importlib
from typing import Tuple

MIN_FASTMCP: Tuple[int, int, int] = (3, 0, 0)
MAX_FASTMCP_EXCLUSIVE: Tuple[int, int, int] = (4, 0, 0)


def _parse_version(version: str) -> Tuple[int, int, int]:
    """Parse a dotted version string into a (major, minor, patch) tuple.

    Returns (0, 0, 0) for unparseable input — the caller treats that as
    too-old, which is the safe-fail direction.
    """
    parts = version.split(".")[:3]
    try:
        # Guard against suffixes like "3.2.4rc1" by stripping trailing
        # non-digits on each component.
        cleaned = []
        for part in parts:
            digits = ""
            for ch in part:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if not digits:
                return (0, 0, 0)
            cleaned.append(int(digits))
        while len(cleaned) < 3:
            cleaned.append(0)
        return (cleaned[0], cleaned[1], cleaned[2])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def assert_fastmcp_compatible() -> None:
    """Raise SystemExit with a fix command if fastmcp is missing or too old.

    Three failure modes, all with actionable messages:
      1. fastmcp not installed at all.
      2. fastmcp present but too old (lacks the submodules 3.x server imports).
      3. fastmcp 3.x present but the wheel is partial / corrupt.
    """
    try:
        fastmcp = importlib.import_module("fastmcp")
    except ImportError as exc:
        raise SystemExit(
            "fastmcp is not installed. Run: pip install -r requirements.txt"
        ) from exc

    version_str = getattr(fastmcp, "__version__", "")
    version_tuple = _parse_version(version_str)
    min_str = ".".join(str(p) for p in MIN_FASTMCP)

    if version_tuple < MIN_FASTMCP:
        displayed = version_str or "<unknown>"
        raise SystemExit(
            f"fastmcp {displayed} is too old (need >= {min_str}). "
            f"Run: pip install --upgrade 'fastmcp>={min_str},<4.0.0'"
        )

    try:
        importlib.import_module("fastmcp.server.tasks.routing")
    except ImportError as exc:
        raise SystemExit(
            f"fastmcp {version_str} install is incomplete: "
            f"missing fastmcp.server.tasks.routing. "
            f"Run: pip install --force-reinstall 'fastmcp>={min_str},<4.0.0'"
        ) from exc
