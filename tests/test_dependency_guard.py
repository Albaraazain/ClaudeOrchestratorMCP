"""Tests for orchestrator._dependency_guard.assert_fastmcp_compatible.

The guard exists because fastmcp 2.x lacks fastmcp.server.tasks.routing, which
fastmcp 3.x's server init imports transitively. With requirements.txt pinned to
3.x this should never fire — but a user installing fastmcp manually, or pip
resolving to a partial wheel, would otherwise hit a confusing
ModuleNotFoundError on the first request. The guard converts that into a
SystemExit at startup with a runnable fix.

Tests are written so each one fails if the guard regresses:
- removing the version compare fails the too-old cases
- removing the routing import check fails the missing-submodule case
- changing the message format fails the message-content asserts
- swallowing ImportError fails test_fastmcp_not_installed_*
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from orchestrator._dependency_guard import (  # noqa: E402
    MIN_FASTMCP,
    _parse_version,
    assert_fastmcp_compatible,
)


# ---------------------------------------------------------------------------
# Helpers: install a fake `fastmcp` into sys.modules for the duration of one
# call, then restore whatever the real test environment had.
# ---------------------------------------------------------------------------


_FASTMCP_KEYS = (
    "fastmcp",
    "fastmcp.server",
    "fastmcp.server.tasks",
    "fastmcp.server.tasks.routing",
)


@pytest.fixture
def isolate_fastmcp(monkeypatch):
    """Snapshot the real fastmcp modules, give the test a clean slate, restore."""
    saved = {name: sys.modules.get(name) for name in _FASTMCP_KEYS}
    for name in _FASTMCP_KEYS:
        sys.modules.pop(name, None)
    yield
    for name in _FASTMCP_KEYS:
        sys.modules.pop(name, None)
    for name, value in saved.items():
        if value is not None:
            sys.modules[name] = value


def _install_fake_fastmcp(version: str | None, *, with_routing: bool):
    fastmcp_mod = types.ModuleType("fastmcp")
    if version is not None:
        fastmcp_mod.__version__ = version
    server_mod = types.ModuleType("fastmcp.server")
    tasks_mod = types.ModuleType("fastmcp.server.tasks")
    fastmcp_mod.server = server_mod
    server_mod.tasks = tasks_mod
    sys.modules["fastmcp"] = fastmcp_mod
    sys.modules["fastmcp.server"] = server_mod
    sys.modules["fastmcp.server.tasks"] = tasks_mod
    if with_routing:
        routing_mod = types.ModuleType("fastmcp.server.tasks.routing")
        tasks_mod.routing = routing_mod
        sys.modules["fastmcp.server.tasks.routing"] = routing_mod
    return fastmcp_mod


# ---------------------------------------------------------------------------
# _parse_version — unit tests on the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("3.2.4", (3, 2, 4)),
        ("3.0.0", (3, 0, 0)),
        ("2.14.7", (2, 14, 7)),
        ("3.2.4rc1", (3, 2, 4)),  # PEP 440 pre-release suffix
        ("3.2", (3, 2, 0)),  # missing patch
        ("3", (3, 0, 0)),  # missing minor and patch
        ("not.a.version", (0, 0, 0)),  # safe-fail
        ("", (0, 0, 0)),
    ],
)
def test_parse_version(version, expected):
    assert _parse_version(version) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_modern_fastmcp_with_routing_passes(isolate_fastmcp):
    _install_fake_fastmcp("3.2.4", with_routing=True)
    assert_fastmcp_compatible()  # must not raise


def test_exact_minimum_version_passes(isolate_fastmcp):
    """The minimum supported version must be accepted, not rejected."""
    min_str = ".".join(str(p) for p in MIN_FASTMCP)
    _install_fake_fastmcp(min_str, with_routing=True)
    assert_fastmcp_compatible()


def test_one_patch_above_minimum_passes(isolate_fastmcp):
    major, minor, patch = MIN_FASTMCP
    _install_fake_fastmcp(f"{major}.{minor}.{patch + 1}", with_routing=True)
    assert_fastmcp_compatible()


# ---------------------------------------------------------------------------
# Too-old version → SystemExit with actionable message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version",
    ["2.0.0", "2.14.7", "1.9.99", "0.0.1", "2.99.99"],
)
def test_too_old_fastmcp_exits_with_actionable_message(isolate_fastmcp, version):
    _install_fake_fastmcp(version, with_routing=False)
    with pytest.raises(SystemExit) as info:
        assert_fastmcp_compatible()

    msg = str(info.value)
    assert version in msg, f"error must name the installed version, got: {msg!r}"
    assert "3.0.0" in msg, f"error must name the required minimum, got: {msg!r}"
    assert "pip install" in msg, f"error must give a runnable fix, got: {msg!r}"


def test_just_below_minimum_is_rejected(isolate_fastmcp):
    """Boundary: the version one patch BELOW the minimum must be rejected."""
    major, minor, _ = MIN_FASTMCP
    if minor == 0 and major > 0:
        below = f"{major - 1}.99.99"
    else:
        below = f"{major}.{max(minor - 1, 0)}.99"
    _install_fake_fastmcp(below, with_routing=True)
    with pytest.raises(SystemExit):
        assert_fastmcp_compatible()


# ---------------------------------------------------------------------------
# Partial / corrupt 3.x install: version OK, submodule missing
# ---------------------------------------------------------------------------


def test_missing_routing_submodule_exits_with_reinstall_hint(isolate_fastmcp):
    _install_fake_fastmcp("3.2.4", with_routing=False)
    with pytest.raises(SystemExit) as info:
        assert_fastmcp_compatible()

    msg = str(info.value)
    assert "fastmcp.server.tasks.routing" in msg, (
        f"error must name the missing submodule, got: {msg!r}"
    )
    assert "force-reinstall" in msg, (
        f"error must suggest reinstall to fix partial wheel, got: {msg!r}"
    )
    assert "3.2.4" in msg


# ---------------------------------------------------------------------------
# Malformed version metadata → fail closed (treat as too-old)
# ---------------------------------------------------------------------------


def test_unparseable_version_treated_as_too_old(isolate_fastmcp):
    _install_fake_fastmcp("not.a.version", with_routing=True)
    with pytest.raises(SystemExit) as info:
        assert_fastmcp_compatible()
    assert "too old" in str(info.value)


def test_missing_version_attribute_treated_as_too_old(isolate_fastmcp):
    _install_fake_fastmcp(version=None, with_routing=True)
    with pytest.raises(SystemExit) as info:
        assert_fastmcp_compatible()
    assert "too old" in str(info.value)


# ---------------------------------------------------------------------------
# Absence: ImportError on `import fastmcp` itself must NOT be swallowed
# ---------------------------------------------------------------------------


def test_fastmcp_not_installed_exits_with_install_hint(monkeypatch, isolate_fastmcp):
    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "fastmcp":
            raise ImportError("No module named 'fastmcp'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(
        "orchestrator._dependency_guard.importlib.import_module",
        fake_import_module,
    )

    with pytest.raises(SystemExit) as info:
        assert_fastmcp_compatible()

    msg = str(info.value)
    assert "fastmcp is not installed" in msg
    assert "pip install" in msg


# ---------------------------------------------------------------------------
# Absence (negative test): on a healthy environment the guard does NOT raise.
# This is the test that fails if someone breaks the guard so badly it always
# raises — covering the "absence of incorrect rejection" axis.
# ---------------------------------------------------------------------------


def test_real_environment_passes_when_fastmcp_is_healthy():
    """Run the guard against the actual installed fastmcp.

    Skipped if fastmcp isn't importable (the dev hasn't run pip install yet).
    """
    try:
        importlib.import_module("fastmcp")
    except ImportError:
        pytest.skip("fastmcp not installed in this environment")
    assert_fastmcp_compatible()
