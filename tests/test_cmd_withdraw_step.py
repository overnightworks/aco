"""`aco withdraw ITEM --step` (`specs/withdraw.spec.md`): a head takes back its own step
through a real GitHub checkout, injecting only at the forge boundary, and through a real
state-ref checkout."""

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import (
    MINIMAL_BLOCK_TOML,
    TRIGGER_WAIT,
    block_body,
    holding_for_the_operator,
)
from board_forge import item_signals
from cli_fixtures import run_cli, set_git_identity
from github_fixtures import FakeForge, serve_forge
from option_cards import card, item_body
from store_fixtures import item_record, seed_state_ref_checkout

from aco import body, forge, protocol, store

PASTE_STEP = {"purpose": "Why.", "paste": "make rotate", "expected": "See it."}
ACTIONS_STEP = {"purpose": "Why.", "actions": "Run the script.", "expected": "See it."}
ACTIONS_STEP_WITH_ANSWER = {**ACTIONS_STEP, "answer": "The code."}
UNTIL_WAIT = {"until": date(2026, 9, 30), "since": date(2026, 8, 31)}
LABEL = "needs-operator"
STATE_REF_ITEM = "aco-000001"


@dataclass
class _LabelRefusingForge(FakeForge):
    """A forge that will not remove a label."""

    def remove_label(self, number: int, label: str) -> None:
        super().remove_label(number, label)
        raise protocol.ClaimError("label refused (simulated)")


def _served(
    raw: str,
    *,
    state: forge.ItemState = forge.ItemState.OPEN,
    is_landing: bool = False,
    author_is_member: bool = True,
) -> FakeForge:
    """A forge whose issue 7 is `raw`, written by a member unless said otherwise."""
    reference = forge.ItemReference(
        state, "Karte", raw, is_landing, author_is_member=author_is_member
    )
    return FakeForge(issue_references={7: reference})


def _waiting(raw: str, wait: Mapping[str, object]) -> str:
    located = body.locate_block(raw)
    return body.replace_block(raw, located, {**located.data, "wait": wait})


def _unheld_data() -> dict[str, object]:
    return dict(body.locate_block(item_body(card())).data)


def _surrounding_bytes(raw: str) -> tuple[str, str]:
    located = body.locate_block(raw)
    return raw[: located.content_start], raw[located.content_end :]


def _stepped(step: dict[str, str] | None) -> str:
    return holding_for_the_operator(item_body(card()), step)


@pytest.mark.usefixtures("github_world")
class TestStepWithdrawn:
    @pytest.mark.parametrize(
        "step",
        [
            pytest.param(PASTE_STEP, id="paste-table"),
            pytest.param(ACTIONS_STEP, id="actions-table"),
            pytest.param(ACTIONS_STEP_WITH_ANSWER, id="actions-table-with-answer"),
            pytest.param(None, id="no-table"),
        ],
    )
    def test_the_wait_the_table_and_the_label_go_and_every_other_byte_stays(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        step: dict[str, str] | None,
    ) -> None:
        """Spec: WITHDRAW-19, WITHDRAW-20, WITHDRAW-22, Never 8 -- one body write of exactly
        the body read, `now` and `next` kept, the label removed after it, a step of any
        stored form."""
        raw = _stepped(step)
        client = serve_forge(monkeypatch, _served(raw))
        result = run_cli(["withdraw", "7", "--step"], capsys)
        written = client.item_bodies[7]
        assert (result.status, result.stdout, result.stderr) == (0, "WITHDRAWN #7 step\n", "")
        assert body.locate_block(written).data == _unheld_data()
        assert _surrounding_bytes(written) == _surrounding_bytes(raw)
        assert (client.body_replacings, client.removed_labels) == ([raw], [(7, LABEL)])
        assert run_cli(["check", "-"], capsys, stdin=written).status == 0

    @pytest.mark.parametrize(
        "served",
        [
            pytest.param(
                _served(_stepped(PASTE_STEP), state=forge.ItemState.CLOSED), id="closed-item"
            ),
            pytest.param(
                _served(_stepped(PASTE_STEP), author_is_member=False), id="non-member-author"
            ),
        ],
    )
    def test_the_state_of_the_item_decides_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        served: FakeForge,
    ) -> None:
        """Spec: WITHDRAW-22 -- a closed item or one a non-member wrote is withdrawn alike."""
        client = serve_forge(monkeypatch, served)
        result = run_cli(["withdraw", "7", "--step"], capsys)
        assert (result.status, result.stdout) == (0, "WITHDRAWN #7 step\n")
        assert body.locate_block(client.item_bodies[7]).data == _unheld_data()

    def test_the_option_line_stays_byte_for_byte(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WITHDRAW-20 -- an open option line next to the step is not touched."""
        raw = _stepped(PASTE_STEP)
        client = serve_forge(monkeypatch, _served(raw))
        run_cli(["withdraw", "7", "--step"], capsys)
        written = client.item_bodies[7]
        assert body.block_expectation_dicts(
            body.locate_block(written).data
        ) == body.block_expectation_dicts(body.locate_block(raw).data)

    def test_a_line_withdrawal_leaves_the_step_the_wait_and_the_label(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WITHDRAW-19 -- `--line N` is the line's form; the step stays."""
        raw = _stepped(PASTE_STEP)
        client = serve_forge(monkeypatch, _served(raw))
        result = run_cli(["withdraw", "7", "--line", "2"], capsys)
        data = body.locate_block(client.item_bodies[7]).data
        assert result.status == 0
        assert (data["wait"], data["step"]) == (
            body.locate_block(raw).data["wait"],
            PASTE_STEP,
        )
        assert client.removed_labels == []


@pytest.mark.usefixtures("github_world")
class TestSignal:
    def test_a_step_withdrawal_touches_no_signal_a_line_withdrawal_does(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Spec: WITHDRAW-18, WAIT-12 -- no signal file for a step; a line's still has one."""
        serve_forge(monkeypatch, _served(_stepped(PASTE_STEP)))
        run_cli(["withdraw", "7", "--step"], capsys)
        after_step = item_signals(tmp_path)
        run_cli(["withdraw", "7", "--line", "2"], capsys)
        assert (after_step, len(item_signals(tmp_path))) == ([], 1)


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(item_body(card()), id="no-wait"),
        pytest.param(_waiting(item_body(card()), UNTIL_WAIT), id="date-wait"),
        pytest.param(_waiting(item_body(card()), TRIGGER_WAIT), id="trigger-wait"),
    ],
)
def test_an_item_with_no_operator_wait_refuses_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
    as_json: bool,
) -> None:
    """Spec: WITHDRAW-21, WITHDRAW-24 -- `no_step` in text and `--json`,
    nothing written."""
    client = serve_forge(monkeypatch, _served(raw))
    result = run_cli(["withdraw", "7", "--step", *(["--json"] if as_json else [])], capsys)
    message = "#7 waits on no step of the operator"
    envelope = {"ok": False, "reason": "no_step", "message": message}
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert (client.body_writes, client.removed_labels) == ([], [])


@pytest.mark.usefixtures("github_world")
def test_json_names_the_item_and_the_step_in_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WITHDRAW-24 -- the envelope's keys in order, no `note` without a
    refused label."""
    serve_forge(monkeypatch, _served(_stepped(PASTE_STEP)))
    result = run_cli(["withdraw", "7", "--step", "--json"], capsys)
    expected = {"ok": True, "reason": "withdrawn", "item": 7, "step": "Decide."}
    assert (result.status, json.loads(result.stdout), list(json.loads(result.stdout))) == (
        0,
        expected,
        list(expected),
    )


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
def test_a_label_the_forge_will_not_remove_keeps_the_written_body_and_warns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    """Spec: WITHDRAW-25, WITHDRAW-24 -- the body stays written, the note names the repair,
    exit 0, `--json` carries the note."""
    raw = _stepped(PASTE_STEP)
    client = serve_forge(
        monkeypatch, _LabelRefusingForge(issue_references=_served(raw).issue_references)
    )
    result = run_cli(["withdraw", "7", "--step", *(["--json"] if as_json else [])], capsys)
    repair = f"gh issue edit 7 --remove-label {LABEL}"
    note = result.stderr.removeprefix("WARNING: ").removesuffix("\n")
    assert (result.status, result.stderr.startswith("WARNING: "), note.endswith(repair)) == (
        0,
        True,
        True,
    )
    assert body.locate_block(client.item_bodies[7]).data == _unheld_data()
    if as_json:
        envelope = json.loads(result.stdout)
        assert (list(envelope), envelope["note"]) == (
            ["ok", "reason", "item", "step", "note"],
            note,
        )


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize(
    ("answer", "sentence"),
    [
        pytest.param(
            forge.ForgeBodyOverwrittenError(7, "2026-11-08T10:05:00Z", "ghost", kept=False),
            "#7 body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
            id="overwritten",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(7, "2026-11-08T10:05:00Z", "ghost", kept=True),
            "#7 body written over a change by ghost at 2026-11-08T10:05:00Z aco had not read; "
            "that change is only in the edit history",
            id="kept",
        ),
        pytest.param(
            forge.ForgeBodyNotVerifiedError(7, "timeout"),
            "#7 body written, not verified (timeout)",
            id="not-verified",
        ),
    ],
)
def test_a_write_the_check_answers_refuses_with_its_sentence_and_keeps_the_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: forge.ForgeBodyWrittenError,
    sentence: str,
) -> None:
    """Spec: WITHDRAW-17, OUT-10 -- the check's sentence, exit 2, and the label stays."""
    served = _served(_stepped(PASTE_STEP))
    served.update_item_body_error = answer
    served.update_item_body_lands_before_error = True
    client = serve_forge(monkeypatch, served)
    result = run_cli(["withdraw", "7", "--step"], capsys)
    assert (result.status, result.stderr, client.removed_labels) == (2, f"ERROR: {sentence}\n", [])


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize(
    ("served", "message"),
    [
        pytest.param(
            _served("", state=forge.ItemState.MISSING), "#7 does not exist", id="missing-item"
        ),
        pytest.param(
            _served(item_body(card()), is_landing=True),
            "#7 is a pull request, not an issue; withdraw needs an issue",
            id="pull-request",
        ),
        pytest.param(
            _served("## Now\nOld prose.\n"),
            "#7 body malformed: aco: no aco block; withdraw needs a valid aco block",
            id="malformed-body",
        ),
    ],
)
def test_a_target_that_is_no_issue_with_a_block_refuses_invalid_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: FakeForge,
    message: str,
) -> None:
    """Spec: WITHDRAW-21, WITHDRAW-10, WITHDRAW-11 -- the refusals of `--line`, before any write."""
    client = serve_forge(monkeypatch, served)
    result = run_cli(["withdraw", "7", "--step", "--json"], capsys)
    envelope = {"ok": False, "reason": "invalid_item", "message": message}
    assert (result.status, result.stderr) == (2, f"ERROR: {message}\n")
    assert json.loads(result.stdout) == envelope
    assert (client.body_writes, client.removed_labels) == ([], [])


@pytest.mark.usefixtures("github_world")
def test_an_unwritable_lock_directory_refuses_unavailable_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec: WITHDRAW-20, WITHDRAW-16 -- the step is withdrawn in the item's turn: a lock that
    cannot be taken refuses `unavailable` with nothing read or written."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    client = serve_forge(monkeypatch, _served(_stepped(PASTE_STEP)))
    result = run_cli(["withdraw", "7", "--step", "--json"], capsys)
    refusal = json.loads(result.stdout)
    prefix = f"ERROR: cannot lock the item at {blocker / 'aco' / 'item-locks'}"
    assert (result.status, result.stderr.startswith(prefix), refusal["reason"]) == (
        2,
        True,
        "unavailable",
    )
    assert (client.body_writes, client.issue_reference_lookups) == ([], [])


class TestStateRef:
    @pytest.fixture(autouse=True)
    def commit_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_git_identity(monkeypatch)

    @pytest.fixture
    def seeded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        bare_remote: Path,
        worktree: Path,
    ) -> None:
        """A state-ref checkout whose item `STATE_REF_ITEM` holds a step."""
        data = {
            **tomllib.loads(MINIMAL_BLOCK_TOML),
            "wait": {"operator": "Decide.", "since": date(2026, 8, 31)},
            "step": PASTE_STEP,
            "record": item_record(title="Karte", state="open", kind="task"),
        }
        content = block_body(body.render_block(data).removesuffix("\n")).encode()
        seed_state_ref_checkout(
            monkeypatch, tmp_path, bare_remote, worktree, {f"{STATE_REF_ITEM}.md": content}
        )

    def test_the_step_goes_and_no_label_is_called(
        self,
        seeded: None,
        bare_remote: Path,
        worktree: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: WITHDRAW-19, WITHDRAW-12 -- the item id in the line, the step gone from the
        stored body; the state-ref forge has no label to call."""
        result = run_cli(["withdraw", STATE_REF_ITEM, "--step"], capsys)
        state = store.fetch_state(worktree=worktree, remote=f"file://{bare_remote}")
        assert state.tip is not None
        stored = store.read_item_files(worktree, state.tip)[f"{STATE_REF_ITEM}.md"].decode()
        assert (result.status, result.stdout, result.stderr) == (
            0,
            f"WITHDRAWN {STATE_REF_ITEM} step\n",
            "",
        )
        assert {"wait", "step"}.isdisjoint(body.locate_block(stored).data)

    def test_repo_is_refused_as_invalid_usage_under_state_ref(
        self, seeded: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WITHDRAW-12 -- `--repo` refuses under `state-ref`, as for `--line`."""
        result = run_cli(["--repo", "acme/items", "withdraw", STATE_REF_ITEM, "--step"], capsys)
        assert (result.status, result.stderr) == (
            2,
            "ERROR: --repo is meaningless under storage = state-ref\n",
        )
        json_result = run_cli(
            ["--repo", "acme/items", "withdraw", STATE_REF_ITEM, "--step", "--json"], capsys
        )
        assert json.loads(json_result.stdout)["reason"] == "invalid_usage"
