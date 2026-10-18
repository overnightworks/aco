"""Test double for a started child process that never reports its exit."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from typing import Any


class UnstoppableProcess:
    """Delegates to a real child but always reports it running, so `wait()` times out."""

    def __init__(self, started: subprocess.Popen[Any]) -> None:
        self._started = started

    def __getattr__(self, name: str) -> Any:
        return getattr(self._started, name)

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(cmd=self._started.args, timeout=timeout or 0)


def reap(children: Iterable[subprocess.Popen[Any]]) -> None:
    """Kill and collect the real children behind unstoppable doubles."""
    for child in children:
        child.kill()
        child.wait()
