"""Shared pytest fixtures and session hooks for the grok-build-bridge tests."""

from __future__ import annotations

import pytest

_NO_TESTS_COLLECTED: int = 5


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Treat "no tests collected" as success while the suite is still empty."""
    if exitstatus == _NO_TESTS_COLLECTED:
        session.exitstatus = 0
