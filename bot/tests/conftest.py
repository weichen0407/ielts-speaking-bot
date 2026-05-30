"""Shared pytest configuration for the local test suite."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

# bot/ is at ielts-speaking-bot/bot/
# project root is ielts-speaking-bot/ which contains the `subagent` package
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Register async marker when pytest-asyncio is not installed."""
    config.addinivalue_line("markers", "asyncio: run test in an asyncio event loop")


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run async tests without requiring pytest-asyncio in lightweight envs.

    The project declares pytest-asyncio in the dev extra, but some local
    environments run without that plugin installed. This hook provides the
    small subset this suite needs: execute coroutine test functions in a fresh
    event loop and pass only the fixtures requested by the test signature.
    """
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    signature = inspect.signature(testfunction)
    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in signature.parameters
        if name in pyfuncitem.funcargs
    }
    asyncio.run(testfunction(**kwargs))
    return True
