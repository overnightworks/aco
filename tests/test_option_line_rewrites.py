"""Every body rewrite keeps option lines value for value (BODY-88): the canonical
rendering itself, then each command that rewrites a block -- `rule`,
`cut`, `rescope`, `item new`/`edit` and the state-ref `[record]` write -- on
old-only, new-only and mixed items, LF and CRLF, `github` and `state-ref`."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, container_issue
from cli_fixtures import real_git, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge
from option_cards import assert_rewritten_alike, card, decide, ruled_card

from aco import body, cmd_item, cmd_rescope, forge, items, session, state_board

OPEN_YES_NO = (
    '[[expectation]]\ntext = "Alte Frage?"\ndefault = "later"\nquestion = "Alt?"\n'
    'example = "Wie bisher."\npicture = """\n<svg xmlns="http://www.w3.org/2000/svg"/>"""\n'
)
RULED_YES_NO = '[[expectation]]\ntext = "Entschieden."\nruling = "no"\nruled_on = 2026-10-01\n'
RECORD = (
    '[record]\ntitle = "Karte"\nstate = "open"\nkind = "task"\nlabels = []\nblocked_by = []\n'
    'created_at = "2026-10-01T00:00:00Z"\nupdated_at = "2026-10-02T00:00:00Z"\n'
)
ITEMS = {
    "old-only": (OPEN_YES_NO, RULED_YES_NO),
    "new-only": (card(), ruled_card()),
    "mixed": (OPEN_YES_NO, card(), RULED_YES_NO, ruled_card()),
}


def item_body(item: str, *, newline: str = "\n", extra: str = "", record: bool = False) -> str:
    lines = "\n".join(ITEMS[item])
    toml_text = MINIMAL_BLOCK_TOML + extra + "\n" + lines + ("\n" + RECORD if record else "")
    return block_body(toml_text.rstrip("\n")).replace("\n", newline)


STORAGES = [
    pytest.param(body.Storage.GITHUB, id="github"),
    pytest.param(body.Storage.STATE_REF, id="state-ref"),
]
NEWLINES = [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")]


@pytest.mark.parametrize("storage", STORAGES)
@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("item", list(ITEMS))
def test_the_canonical_rendering_reads_back_every_value(
    item: str, newline: str, storage: body.Storage
) -> None:
    """Spec: BODY-88 -- parse(render(parse(body))) is parse(body); rendering again is a no-op."""
    raw = item_body(item, newline=newline, record=storage is body.Storage.STATE_REF)
    located = body.locate_block(raw)
    rewritten = body.replace_block(raw, located, located.data)
    assert body.locate_block(rewritten).data == located.data
    assert_rewritten_alike(raw, rewritten, storage)


def written_keys(raw: str) -> list[str]:
    """Each table header and key of `raw` in the order it is written."""
    return [
        line.split(" = ")[0]
        for line in raw.splitlines()
        if line.startswith("[") or (" = " in line and not line.startswith("<"))
    ]


def test_a_rewrite_writes_the_keys_in_the_order_the_card_names() -> None:
    """Spec: BODY-88 -- the item body's own key order is the order a rewrite writes."""
    raw = block_body((MINIMAL_BLOCK_TOML + "\n" + card() + "\n" + ruled_card()).rstrip("\n"))
    located = body.locate_block(raw)
    assert written_keys(body.replace_block(raw, located, located.data)) == written_keys(raw)


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> Path:
    assert_github_world(github_clone, bare_remote)
    return github_clone


@pytest.mark.usefixtures(github_world.__name__)
@pytest.mark.parametrize("newline", NEWLINES)
def test_rule_keeps_option_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    newline: str,
) -> None:
    """Spec: BODY-88, RULE-12 -- `rule` on an option line rewrites only that line."""
    raw = item_body("mixed", newline=newline)
    reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", raw)
    client = serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))
    ruled = run_cli(["rule", "7", *decide("A", "chat", line=2)], capsys)
    assert ruled.status == 0, ruled.stderr
    written = client.item_bodies[7]
    expectations_before = body.block_expectation_dicts(body.locate_block(raw).data)
    expectations_after = body.block_expectation_dicts(body.locate_block(written).data)
    assert expectations_after[2:] == expectations_before[2:]
    assert expectations_after[0] == expectations_before[0]
    assert (expectations_after[1]["ruling"], ("\r\n" in written) is ("\r\n" in raw)) == ("A", True)


@pytest.mark.usefixtures(github_world.__name__)
@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("item", ["mixed", "new-only"])
class TestCommandRewrites:
    def test_cut_keeps_option_lines(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        github_world: Path,
        item: str,
        newline: str,
    ) -> None:
        """Spec: BODY-88, CUT-11 -- removing a slice row re-renders the container's block."""
        track_board_config(github_world, 'body_contract = "block"\n')
        assert real_git(github_world, "ls-files", ".aco/board.toml").stdout == ".aco/board.toml\n"
        row = '\n[[slice]]\nindex = 1\ntitle = "Slice A"\ndone_when = "D"\n'
        raw = item_body(item, newline=newline, extra=row)
        container = dataclasses.replace(container_issue(79, ""), body=raw)
        client = serve_forge(monkeypatch, FakeForge(board_issues=(container,)))
        result = run_cli(["cut", "79"], capsys)
        assert result.status == 0, result.stderr
        assert "[[slice]]" not in client.item_bodies[79]
        assert_rewritten_alike(raw, client.item_bodies[79], body.Storage.GITHUB)

    def test_item_new_keeps_option_lines(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        item: str,
        newline: str,
    ) -> None:
        """Spec: BODY-88, ITEM-62 -- a block flag re-renders the piped body's block."""
        raw = item_body(item, newline=newline)
        client = serve_forge(monkeypatch, FakeForge())
        command = ["item", "new", "--title", "Neue Karte", "--size", "S"]
        result = run_cli(command, capsys, stdin=raw)
        assert result.status == 0, result.stderr
        written = client.created_issues[0][1]
        assert 'size = "S"' in written
        assert_rewritten_alike(raw, written, body.Storage.GITHUB)


@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("item", list(ITEMS))
def test_item_edit_and_rescope_writes_keep_option_lines(item: str, newline: str) -> None:
    """Spec: BODY-88 -- the block writes behind `item edit` and `rescope`."""
    raw = item_body(item, newline=newline)
    located = body.locate_block(raw)
    client = FakeForge()
    cmd_item._write_block_data(client, 7, raw, located, {**located.data, "next": "Weiter."})
    assert_rewritten_alike(raw, client.item_bodies[7], body.Storage.GITHUB)
    rescoped = cmd_rescope._RescopedItemBody(number=8, text=raw, located=located, whole=None)
    context = cast(session.RunContext, SimpleNamespace(forge_writer=client))
    cmd_rescope._write_rescoped_body(context, rescoped, ("src/a.py", "src/b.py"), "Ein Grund.")
    assert_rewritten_alike(raw, client.item_bodies[8], body.Storage.GITHUB)


@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("item", list(ITEMS))
@pytest.mark.parametrize(
    ("existing", "state", "closed_at"),
    [
        pytest.param(False, items.RecordState.OPEN, None, id="create"),
        pytest.param(True, items.RecordState.OPEN, None, id="update"),
        pytest.param(True, items.RecordState.CLOSED, "2026-10-03T00:00:00Z", id="close"),
    ],
)
def test_the_state_ref_record_write_keeps_option_lines(
    item: str, newline: str, existing: bool, state: items.RecordState, closed_at: str | None
) -> None:
    """Spec: BODY-88 -- the one `[record]` composer behind create, update and close."""
    raw = item_body(item, newline=newline, record=existing)
    record = items.ItemRecord(
        number=1,
        title="Karte",
        state=state,
        kind="task",
        labels=(),
        blocked_by=(),
        parent=None,
        origin=None,
        created_at="2026-10-01T00:00:00Z",
        updated_at="2026-10-03T00:00:00Z",
        closed_at=closed_at,
    )
    written = state_board._with_record(raw, record)
    assert_rewritten_alike(raw, written, body.Storage.STATE_REF)
    assert state_board._with_record(written, record) == written
