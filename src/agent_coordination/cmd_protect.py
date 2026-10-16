"""The `protect` command (`specs/protect.spec.md`): the PreToolUse write gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import protect
from .session import board_config, trunk_lane_shared


def _canonical_remote_name(toplevel: Path) -> str:
    """The configured `canonical_remote` of the checkout at `toplevel`, for
    `protect` (handed into `protect.judge` as `canonical_remote_for`), which
    judges from its own payload's resolved checkout and never builds a
    `RunContext` (issue #457)."""
    return board_config(toplevel).canonical_remote


def _checkout_trunk_lane_shared(toplevel: Path) -> tuple[str, ...]:
    """The lane-shared files the trunk of the checkout at `toplevel` names,
    for `protect` (handed into `protect.judge` as `lane_shared_for`, issue
    #575), resolved over that checkout's own canonical remote."""
    return trunk_lane_shared(_canonical_remote_name(toplevel), toplevel)


def _hook_payload() -> dict[str, object] | None:
    try:
        payload = json.loads(sys.stdin.read())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def run() -> int:
    # Grok fail-opens on crash or non-JSON hook output; deny instead of raising.
    try:
        payload = _hook_payload()
        verdict = protect.judge(
            payload,
            canonical_remote_for=_canonical_remote_name,
            lane_shared_for=_checkout_trunk_lane_shared,
        )
    except Exception as error:
        verdict = protect.Verdict.deny(str(error))
    if verdict.stdout_text is not None:
        print(verdict.stdout_text)
    if verdict.stderr_text is not None:
        print(verdict.stderr_text, file=sys.stderr)
    return verdict.exit_code
