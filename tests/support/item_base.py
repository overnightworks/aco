"""The base a whole-body `aco item edit` names, taken from what `aco item show --json`
printed, never recomputed from the body."""

import json

import pytest
from cli_fixtures import CliRun, run_cli


def shown_body_hash(item: str, capsys: pytest.CaptureFixture[str], *prefix: str) -> str:
    """The `body_hash` of `item` as `item show --json` printed it, in the success
    envelope or in a malformed item's refusal (ITEM-38); `prefix` is any global flags."""
    shown = run_cli([*prefix, "item", "show", item, "--json"], capsys)
    return str(json.loads(shown.stdout)["body_hash"])


def edit_with_base(item: str, capsys: pytest.CaptureFixture[str], *prefix: str) -> list[str]:
    """The arguments of a whole-body `item edit` of `item` against the body it has now."""
    return [*prefix, "item", "edit", item, "--base", shown_body_hash(item, capsys, *prefix)]


CURRENT_BASE = "<current-base>"


def with_current_base(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> list[str]:
    """`arguments` with `CURRENT_BASE` replaced by the hash `item show --json` prints for the
    item they edit, so a parametrized case names a base before any item exists."""
    if CURRENT_BASE not in arguments:
        return arguments
    item = arguments[arguments.index("edit") + 1]
    return [shown_body_hash(item, capsys) if part == CURRENT_BASE else part for part in arguments]


def edit_item(item: str, capsys: pytest.CaptureFixture[str], *, stdin: str) -> CliRun:
    """A whole-body `item edit` of `item` that pipes `stdin` against the body it has now."""
    return run_cli(edit_with_base(item, capsys), capsys, stdin=stdin)
