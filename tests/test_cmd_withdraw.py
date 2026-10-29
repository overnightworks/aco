"""`aco withdraw` (`specs/withdraw.spec.md`) through a real GitHub checkout,
injecting only at the forge boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli, track_board_config
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    SECOND_CARD,
    YES_NO_LINE,
    card,
    card_body,
    decide,
    item_body,
    returned_card,
    ruled_card,
)

from aco import body, forge, github, store
from aco.expectation_grammar import WITHDRAWN_ON

WITHDRAWN_LINE = '[[expectation]]\ntext = "Zurück"\nwithdrawn_on = 2026-08-01\n'


def three_lines(third: str = SECOND_CARD, *, newline: str = "\n") -> str:
    """Issue #7: line 1 a ruled yes/no line, line 2 an open option line, line 3 `third`."""
    return card_body(third, before="\n" + YES_NO_LINE + "\n" + card(), newline=newline)


def item_forge(
    raw: str,
    *,
    state: forge.ItemState = forge.ItemState.OPEN,
    is_landing: bool = False,
    fail_update_item_body: bool = False,
    read_error: forge.ForgeError | None = None,
) -> FakeForge:
    """A forge whose issue 7 is `raw`; `read_error` fails its one item read."""
    reference = forge.ItemReference(state, "Karte", raw, is_landing)
    return FakeForge(
        issue_references={7: reference},
        fail_update_item_body=fail_update_item_body,
        scripted_item_reads=[] if read_error is None else [read_error],
    )


def entries(raw: str) -> list[dict[str, object]]:
    return body.block_expectation_dicts(body.locate_block(raw).data)


def tombstone(entry: dict[str, object]) -> dict[str, object]:
    """`entry` as withdrawn on the frozen day: its text and the date, nothing else."""
    return {"text": entry["text"], WITHDRAWN_ON: FROZEN_CLI_NOW.date()}


def surrounding_bytes(raw: str) -> tuple[str, str]:
    located = body.locate_block(raw)
    return raw[: located.content_start], raw[located.content_end :]


@pytest.mark.usefixtures("github_world")
class TestWithdrawn:
    @pytest.mark.parametrize(
        "newline", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")]
    )
    @pytest.mark.parametrize(
        ("third", "line", "sentence"),
        [
            pytest.param(SECOND_CARD, 2, "WITHDRAWN #7 line 2; 1 line(s) still open\n", id="open"),
            pytest.param(
                returned_card(), 3, "WITHDRAWN #7 line 3; 1 line(s) still open\n", id="returned"
            ),
        ],
    )
    def test_one_line_becomes_its_text_and_today_and_nothing_else_changes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        third: str,
        line: int,
        sentence: str,
        newline: str,
    ) -> None:
        """Spec: WITHDRAW-01, WITHDRAW-02, Never 2, Never 3 -- one entry rewritten, every
        other entry and every byte outside the block kept, the body still valid."""
        freeze_cli_now(monkeypatch)
        raw = three_lines(third, newline=newline)
        client = serve_forge(monkeypatch, item_forge(raw))
        result = run_cli(["withdraw", "7", "--line", str(line)], capsys)
        written = client.item_bodies[7]
        expected = entries(raw)
        expected[line - 1] = tombstone(expected[line - 1])
        located = body.locate_block(written)
        assert (result.status, result.stdout, result.stderr) == (0, sentence, "")
        assert entries(written) == expected
        assert surrounding_bytes(written) == surrounding_bytes(raw)
        assert ("\r\n" in written) is (newline == "\r\n")
        assert body.replace_block(written, located, located.data) == written
        assert run_cli(["check", "-"], capsys, stdin=written).status == 0

    def test_json_names_the_line_its_date_and_the_open_count(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WITHDRAW-03, OUT-01 -- the envelope's keys in order."""
        freeze_cli_now(monkeypatch)
        serve_forge(monkeypatch, item_forge(three_lines()))
        result = run_cli(["withdraw", "7", "--line", "2", "--json"], capsys)
        expected = {
            "ok": True,
            "reason": "withdrawn",
            "item": 7,
            "index": 2,
            "withdrawn_on": FROZEN_CLI_NOW.date().isoformat(),
            "open": 1,
        }
        assert (result.status, result.stdout) == (0, json.dumps(expected) + "\n")

    @pytest.mark.parametrize(
        ("as_json", "printed"),
        [
            pytest.param(False, "WITHDRAWN #7 lines 2, 3; 0 line(s) still open\n", id="text"),
            pytest.param(
                True,
                json.dumps(
                    {
                        "ok": True,
                        "reason": "withdrawn",
                        "item": 7,
                        "lines": [{"index": 2}, {"index": 3}],
                        "withdrawn_on": FROZEN_CLI_NOW.date().isoformat(),
                        "open": 0,
                    }
                )
                + "\n",
                id="json",
            ),
        ],
    )
    def test_several_lines_land_in_one_write_with_one_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        printed: str,
    ) -> None:
        """Spec: WITHDRAW-04, WITHDRAW-05 -- an open and a returned line together."""
        freeze_cli_now(monkeypatch)
        raw = three_lines(returned_card())
        client = serve_forge(monkeypatch, item_forge(raw))
        flags = ["--json"] if as_json else []
        result = run_cli(["withdraw", "7", "--line", "2", "--line", "3", *flags], capsys)
        before = entries(raw)
        assert (result.status, result.stdout) == (0, printed)
        assert len(client.body_writes) == 1
        assert entries(client.item_bodies[7]) == [before[0], *map(tombstone, before[1:])]

    def test_a_withdrawn_line_then_refuses_a_ruling(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-37 -- once withdrawn, nobody answers the line."""
        freeze_cli_now(monkeypatch)
        client = serve_forge(monkeypatch, item_forge(three_lines()))
        run_cli(["withdraw", "7", "--line", "2"], capsys).expect_success()
        serve_forge(monkeypatch, item_forge(client.item_bodies[7]))
        refused = run_cli(["rule", "7", *decide("A", "chat")], capsys)
        assert refused.stderr == "ERROR: line 2 was withdrawn by its head\n"


_RULED_FOR_GOOD = "is already ruled; a ruled line stays as it is"
_WITH_A_TOMBSTONE = card_body(card(), before="\n" + WITHDRAWN_LINE)


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    ("served", "lines", "message", "reason"),
    [
        pytest.param(
            partial(item_forge, _WITH_A_TOMBSTONE),
            ("3",),
            "line 3 out of range: this item has 2 expectation line(s)",
            "line_out_of_range",
            id="out-of-range-counting-the-tombstone",
        ),
        pytest.param(
            partial(item_forge, _WITH_A_TOMBSTONE),
            ("0",),
            "line 0 out of range: this item has 2 expectation line(s)",
            "line_out_of_range",
            id="out-of-range-zero",
        ),
        pytest.param(
            partial(item_forge, _WITH_A_TOMBSTONE),
            ("1",),
            "line 1 was withdrawn by its head",
            "already_withdrawn",
            id="already-withdrawn",
        ),
        pytest.param(
            partial(item_forge, item_body(ruled_card())),
            ("2",),
            f"line 2 {_RULED_FOR_GOOD}",
            "already_ruled",
            id="ruled-option-line",
        ),
        pytest.param(
            partial(item_forge, item_body(card())),
            ("1",),
            f"line 1 {_RULED_FOR_GOOD}",
            "already_ruled",
            id="ruled-yes-no-line",
        ),
        pytest.param(
            partial(item_forge, item_body(card())),
            ("2", "1"),
            f"line 1 {_RULED_FOR_GOOD}",
            "already_ruled",
            id="second-named-line-ruled",
        ),
        pytest.param(
            partial(item_forge, item_body(card())),
            ("5", "1"),
            "line 5 out of range: this item has 2 expectation line(s)",
            "line_out_of_range",
            id="out-of-range-written-first",
        ),
        pytest.param(
            partial(item_forge, item_body(card())),
            ("1", "5"),
            f"line 1 {_RULED_FOR_GOOD}",
            "already_ruled",
            id="ruled-written-first",
        ),
        pytest.param(
            partial(item_forge, "", state=forge.ItemState.MISSING),
            ("1",),
            "#7 does not exist",
            "invalid_item",
            id="missing-item",
        ),
        pytest.param(
            partial(item_forge, item_body(card()), is_landing=True),
            ("2",),
            "#7 is a pull request, not an issue; withdraw needs an issue",
            "invalid_item",
            id="pull-request",
        ),
        pytest.param(
            partial(item_forge, "## Now\nOld prose.\n"),
            ("1",),
            "#7 body malformed: aco: no aco block; withdraw needs a valid aco block",
            "invalid_item",
            id="malformed-body",
        ),
        pytest.param(
            partial(item_forge, item_body(card()), fail_update_item_body=True),
            ("2",),
            "update item body failed (simulated)",
            "unavailable",
            id="write-failure",
        ),
        pytest.param(
            partial(item_forge, item_body(card()), read_error=forge.ForgeError("item read failed")),
            ("2",),
            "item read failed",
            "unavailable",
            id="read-failure",
        ),
    ],
)
def test_refusal_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: Callable[[], FakeForge],
    lines: tuple[str, ...],
    message: str,
    reason: str,
    as_json: bool,
) -> None:
    """Spec: WITHDRAW-04, WITHDRAW-06..08, WITHDRAW-10, WITHDRAW-11, WITHDRAW-13,
    WITHDRAW-14, Never 1 -- the first refusal in written order, and no write."""
    client = serve_forge(monkeypatch, served())
    named = [flag for index in lines for flag in ("--line", index)]
    result = run_cli(["withdraw", "7", *named, *(["--json"] if as_json else [])], capsys)
    envelope = {"ok": False, "reason": reason, "message": message}
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert client.item_bodies == {}


@pytest.mark.usefixtures("github_world")
def test_a_line_named_twice_refuses_before_any_forge_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WITHDRAW-09 -- `invalid_usage`, the item never read."""
    client = serve_forge(monkeypatch, item_forge(three_lines()))
    result = run_cli(["withdraw", "7", "--line", "2", "--line", "2", "--json"], capsys)
    message = "line 2 is named twice"
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert json.loads(result.stdout) == {"ok": False, "reason": "invalid_usage", "message": message}
    assert client.issue_reference_lookups == []


def test_repo_under_state_ref_refuses_before_the_forge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], clone: Path
) -> None:
    """Spec: WITHDRAW-12, PIN-04 -- `--repo` names no state-ref store."""
    monkeypatch.chdir(clone)
    track_board_config(clone, 'storage = "state-ref"\n')

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("the --repo refusal must precede the forge")

    monkeypatch.setattr(github, "GitHubForge", forbidden)
    monkeypatch.setattr(store, "fetch_state", forbidden)
    result = run_cli(["--repo", "acme/items", "withdraw", "258", "--line", "1", "--json"], capsys)
    message = "--repo is meaningless under storage = state-ref"
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert json.loads(result.stdout) == {"ok": False, "reason": "invalid_usage", "message": message}


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(
            ["withdraw", "7"],
            "aco withdraw: error: the following arguments are required: --line",
            id="no-line",
        ),
        pytest.param(
            ["withdraw", "7", "--line", "2", "--via", "chat"],
            "aco: error: unrecognized arguments: --via chat",
            id="via",
        ),
        pytest.param(
            ["withdraw", "7", "--line", "2", "--card-hash", "sha256:0"],
            "aco: error: unrecognized arguments: --card-hash sha256:0",
            id="card-hash",
        ),
    ],
)
def test_the_parser_refuses_before_the_command(
    capsys: pytest.CaptureFixture[str], arguments: list[str], sentence: str
) -> None:
    """Spec: WITHDRAW-14, Never 4 -- `--line` is required; `--via` and `--card-hash` are no
    flags of this command."""
    result = run_cli(arguments, capsys)
    assert (result.status, result.stderr.splitlines()[-1]) == (2, sentence)


def test_help_names_each_flag_with_a_help_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: WITHDRAW-01 -- `--line` and `--json`, each with its own help line."""
    shown = " ".join(run_cli(["withdraw", "--help"], capsys).stdout.split())
    assert "--line N the 1-based expectation line index" in shown
    assert "--json print the result as JSON" in shown
