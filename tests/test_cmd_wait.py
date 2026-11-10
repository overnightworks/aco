"""`aco wait` (`specs/wait.spec.md`) through a real GitHub checkout, injecting only
at the forge boundary and at the pause and clock the command takes."""

import json
import re
from pathlib import Path

import pytest
from cli_fixtures import run_cli, track_board_config
from option_cards import (
    decide,
    group_body,
    returned_card,
    ruled_card,
    unclear,
)
from wait_fixtures import ITEM, install, reads_of, serve_item, serve_snapshots

from aco import body, cmd_wait, forge, github, store

WITHDRAWN_LINE = '[[expectation]]\ntext = "Zurück"\nwithdrawn_on = 2026-08-01\n'
DATE = r"\d{4}-\d{2}-\d{2}"


def open_reference(raw: str, *, is_landing: bool = False) -> forge.ItemReference:
    return forge.ItemReference(forge.ItemState.OPEN, "Karte", raw, is_landing)


@pytest.mark.usefixtures("github_world")
class TestWaiting:
    @pytest.mark.parametrize(
        ("raw", "named", "printed"),
        [
            pytest.param(
                group_body(), ["1"], r"CHANGED #7 line 1: ruled no 2026-10-01\n", id="yes-no"
            ),
            pytest.param(
                group_body(returned_card()),
                ["3"],
                rf"CHANGED #7 line 3: with head {DATE}\n",
                id="returned",
            ),
            pytest.param(
                group_body(WITHDRAWN_LINE),
                ["3"],
                r"CHANGED #7 line 3: withdrawn 2026-08-01\n",
                id="withdrawn",
            ),
            pytest.param(
                group_body(),
                ["1", "1"],
                r"CHANGED #7 line 1: ruled no 2026-10-01\n",
                id="named-twice-counts-once",
            ),
            pytest.param(
                group_body(WITHDRAWN_LINE),
                ["2", "1", "3"],
                r"CHANGED #7 line 1: ruled no 2026-10-01\n"
                r"CHANGED #7 line 3: withdrawn 2026-08-01\n",
                id="several-in-the-items-order",
            ),
        ],
    )
    def test_a_line_not_open_at_the_start_ends_it_at_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        raw: str,
        named: list[str],
        printed: str,
    ) -> None:
        """Spec: WAIT-01, WAIT-03 -- the command reads once and never pauses."""
        client = serve_item(monkeypatch, open_reference(raw))
        ticks = install(monkeypatch, reads_of(client))
        arguments = [argument for line in named for argument in ("--line", line)]
        result = run_cli(["wait", "7", *arguments], capsys)
        assert (result.status, result.stderr, ticks.pauses) == (0, "", [])
        assert re.fullmatch(printed, result.stdout)
        assert client.issue_reference_lookups == [ITEM]

    def test_json_names_the_item_and_each_changed_line_with_its_state(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-02 -- the envelope's keys in order."""
        client = serve_item(monkeypatch, open_reference(group_body()))
        install(monkeypatch, reads_of(client))
        result = run_cli(["wait", "7", "--line", "1", "--json"], capsys)
        expected = {
            "ok": True,
            "reason": "changed",
            "item": 7,
            "lines": [{"index": 1, "state": "ruled no 2026-10-01"}],
        }
        assert (result.status, result.stdout) == (0, json.dumps(expected) + "\n")

    @pytest.mark.parametrize(
        ("changer", "state"),
        [
            pytest.param(["rule", "7", *decide("A", "chat")], rf"ruled A {DATE}", id="ruled"),
            pytest.param(["rule", "7", *unclear()], rf"with head {DATE}", id="returned"),
            pytest.param(["withdraw", "7", "--line", "2"], rf"withdrawn {DATE}", id="withdrawn"),
        ],
    )
    def test_a_line_ruled_returned_or_withdrawn_while_it_waits_ends_it_after_one_more_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        changer: list[str],
        state: str,
    ) -> None:
        """Spec: WAIT-01, WAIT-07, WAIT-12 -- the real write signals; no read in between."""
        store = serve_snapshots(monkeypatch, open_reference(group_body()))
        ticks = install(monkeypatch, store.reads)
        reads_by_the_change: list[int] = []

        def change() -> None:
            before = store.reads()
            assert run_cli(changer, capsys).status == 0
            reads_by_the_change.append(store.reads() - before)

        ticks.afterwards[3] = change
        result = run_cli(["wait", "7", "--line", "2", "--line", "3"], capsys)
        assert (result.status, result.stderr, ticks.reads_seen[:3]) == (0, "", [1, 1, 1])
        assert re.fullmatch(rf"CHANGED #7 line 2: {state}\n", result.stdout)
        assert store.reads() == 1 + sum(reads_by_the_change) + 1

    def test_a_line_changed_by_hand_ends_it_at_the_slow_read_and_not_before(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-08, WAIT-07 -- no signal moves; the item is read again every
        `ITEM_READ_SECONDS`."""
        store = serve_snapshots(monkeypatch, open_reference(group_body()))
        ticks = install(monkeypatch, store.reads)
        ticks.afterwards[10] = lambda: store.references.update(
            {ITEM: open_reference(group_body(ruled_card()))}
        )
        result = run_cli(["wait", "7", "--line", "3"], capsys)
        assert (result.status, result.stderr) == (0, "")
        assert re.fullmatch(rf"CHANGED #7 line 3: ruled A {DATE}\n", result.stdout)
        assert set(ticks.reads_seen) == {1}
        assert ticks.now >= cmd_wait.ITEM_READ_SECONDS
        assert store.reads() == 2

    def test_a_forge_failure_while_it_waits_refuses_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-10 -- a later read that fails ends the command loudly."""
        client = serve_item(monkeypatch, open_reference(group_body()))
        client.scripted_item_reads.extend([None, forge.ForgeError("the forge is down")])
        install(monkeypatch, reads_of(client))
        result = run_cli(["wait", "7", "--line", "2", "--json"], capsys)
        message = "the forge is down"
        assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
        assert json.loads(result.stdout) == {
            "ok": False,
            "reason": "unavailable",
            "message": message,
        }


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    ("reference", "line", "reason", "message"),
    [
        pytest.param(
            open_reference(group_body()),
            "4",
            "line_out_of_range",
            "line 4 out of range: this item has 3 expectation line(s)",
            id="out-of-range",
        ),
        pytest.param(
            forge.ItemReference(forge.ItemState.MISSING),
            "2",
            "invalid_item",
            "#7 does not exist",
            id="missing",
        ),
        pytest.param(
            open_reference(group_body(), is_landing=True),
            "2",
            "invalid_item",
            "#7 is a pull request, not an issue; wait needs an issue",
            id="pull-request",
        ),
        pytest.param(
            forge.ItemReference(forge.ItemState.CLOSED, "Karte", group_body()),
            "2",
            "invalid_item",
            "#7 is closed; there is nothing to wait for",
            id="closed",
        ),
    ],
)
def test_a_refusal_comes_before_any_waiting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reference: forge.ItemReference,
    line: str,
    reason: str,
    message: str,
    as_json: bool,
) -> None:
    """Spec: WAIT-04, WAIT-05, WAIT-11 -- exit 2, the reason of the table, no pause."""
    client = serve_item(monkeypatch, reference)
    ticks = install(monkeypatch, reads_of(client))
    result = run_cli(["wait", "7", "--line", line, *(["--json"] if as_json else [])], capsys)
    envelope = {"ok": False, "reason": reason, "message": message}
    assert (result.status, result.stderr, ticks.pauses) == (2, f"ERROR: {message}\n", [])
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")


@pytest.mark.usefixtures("github_world")
def test_a_malformed_body_refuses_naming_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-04 -- the body defect sentence, then what `wait` needs."""
    client = serve_item(monkeypatch, open_reference("no block here"))
    install(monkeypatch, reads_of(client))
    result = run_cli(["wait", "7", "--line", "1"], capsys)
    assert (result.status, result.stdout) == (2, "")
    assert result.stderr.startswith("ERROR: #7 ")
    assert result.stderr.endswith("; wait needs a valid aco block\n")


@pytest.mark.usefixtures("github_world")
def test_a_forge_failure_at_the_start_refuses_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-10 -- the first read fails."""
    client = serve_item(monkeypatch, open_reference(group_body()))
    client.scripted_item_reads.append(forge.ForgeError("the forge is down"))
    ticks = install(monkeypatch, reads_of(client))
    result = run_cli(["wait", "7", "--line", "2", "--json"], capsys)
    assert (result.status, ticks.pauses) == (2, [])
    assert json.loads(result.stdout)["reason"] == "unavailable"


def test_repo_under_state_ref_refuses_before_the_forge(
    clone: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-06, PIN-04 -- `--repo` names no state-ref store."""
    monkeypatch.chdir(clone)
    track_board_config(clone, f'storage = "{body.Storage.STATE_REF.value}"\n')

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("the context refusal must precede this boundary")

    monkeypatch.setattr(github, "GitHubForge", forbidden)
    monkeypatch.setattr(store, "fetch_state", forbidden)
    result = run_cli(["--repo", "acme/items", "wait", "258", "--line", "1", "--json"], capsys)
    message = "--repo is meaningless under storage = state-ref"
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert json.loads(result.stdout) == {"ok": False, "reason": "invalid_usage", "message": message}


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(
            ["wait", "7"],
            "aco wait: error: the following arguments are required: --line",
            id="no-line",
        ),
        pytest.param(
            ["wait", "7", "--line", "2", "--timeout", "5"],
            "aco: error: unrecognized arguments: --timeout 5",
            id="no-timeout",
        ),
    ],
)
def test_the_parser_refuses_a_missing_line_and_a_timeout(
    capsys: pytest.CaptureFixture[str], arguments: list[str], sentence: str
) -> None:
    """Spec: WAIT-09, Never 2 -- `--line` is required and the command has no timeout flag."""
    result = run_cli(arguments, capsys)
    assert (result.status, result.stdout) == (2, "")
    assert sentence in result.stderr


def test_help_lists_the_flags_each_with_a_help_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: the header -- `--line` and `--json`, each with a help line."""
    result = run_cli(["wait", "--help"], capsys)
    assert (result.status, "--line" in result.stdout, "--json" in result.stdout) == (0, True, True)
    assert "the 1-based expectation line index" in result.stdout


@pytest.mark.usefixtures("github_world")
def test_a_signal_that_cannot_be_read_refuses_unavailable_before_the_item_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec: WAIT-10 -- a state directory that is no directory names the signal's path."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    client = serve_item(monkeypatch, open_reference(group_body()))
    ticks = install(monkeypatch, reads_of(client))
    result = run_cli(["wait", "7", "--line", "2", "--json"], capsys)
    refusal = json.loads(result.stdout)
    prefix = f"cannot watch the item's signal at {blocker / 'aco' / 'item-signals'}"
    assert (result.status, refusal["reason"]) == (2, "unavailable")
    assert refusal["message"].startswith(prefix)
    assert (ticks.pauses, client.issue_reference_lookups) == ([], [])
