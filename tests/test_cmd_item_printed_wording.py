"""Each row of `specs/item.spec.md`'s table of printed wording, driven through the real
`aco item` command: the sentence it prints or refuses with, its exit status and its stream.
The case ids are the rows' ids. The forge is the only fake; `storage = "state-ref"` rows run
on a real checkout and a bare `file://` remote."""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pytest
from board_fixtures import (
    MINIMAL_BLOCK_TOML,
    REPOSITORY,
    block_body,
    board_issue,
    complete_contract,
    container_issue,
)
from cli_fixtures import (
    devnull_on_stdin,
    run_cli,
    set_git_identity,
)
from github_fixtures import FakeForge, serve_forge
from item_base import CURRENT_BASE, with_current_base
from store_fixtures import item_record, seed_state_ref_checkout

from aco import body, forge, store

type Written = Callable[[], object]

CONTAINER = 79
TASK_ITEM = 484
EDITED_ITEM = 72
LOOK_ALIKE = 951
STORED = block_body(MINIMAL_BLOCK_TOML)
REPLACEMENT = block_body(MINIMAL_BLOCK_TOML, before="Replacement prose.\n\n")
PIPED_BODY = complete_contract("Ship it.", size="S")

PARENT_ID = "aco-000001"
CHILD_ID = "aco-000002"
MALFORMED_ID = "aco-000003"
NO_BLOCK = b"prose, no block\n"


class World(StrEnum):
    """The fixture that arranges the checkout a row runs in."""

    GITHUB = "github_items"
    STATE_REF = "state_ref_items"


@dataclass(frozen=True)
class Row:
    """One printed sentence: the arguments and stdin that trigger it, the command run first,
    the forge's own failure, and the exact status and stream text expected."""

    arguments: tuple[str, ...]
    stderr: str = ""
    stdout: str = ""
    status: int = 2
    stdin: str | None = None
    first: tuple[str, ...] | None = None
    forge_flags: tuple[str, ...] = ()
    world: World = World.GITHUB
    malformed_item: bool = False
    writes: bool = False


def refused(sentence: str) -> str:
    return f"ERROR: {sentence}\n"


def state_ref_body(prose: str, **record: object) -> str:
    """A valid state-ref item body whose `[record]` is `record` over a task's defaults."""
    fields = {"title": "Karte", "state": "open", "kind": "task"} | record
    data = {**tomllib.loads(MINIMAL_BLOCK_TOML), "record": item_record(**fields)}  # type: ignore[arg-type]
    return block_body(body.render_block(data).removesuffix("\n"), before=f"{prose}\n\n")


NEW = ("item", "new", "--title", "Write the docs")
EDIT_TASK = ("item", "edit", str(TASK_ITEM))
EDIT_CHILD = ("item", "edit", CHILD_ID)
TWICE = ("--size", "S")

ROWS = {
    "ITEM-06": Row(
        ("item", "new", "--title", "T", "--origin", "nope"),
        refused("'nope' is not an origin; use forge#n or host/owner/repo#n, e.g. gitlab#42"),
    ),
    "ITEM-36": Row(("item", "new", "--title", "  "), refused("--title must be a non-empty string")),
    "ITEM-59": Row(
        (*NEW, "--size", "M"),
        refused("""--size "M" contradicts the piped block's size = "S\""""),
        stdin=PIPED_BODY,
    ),
    "ITEM-29-not-open": Row(
        (*NEW, "--parent", "81"), refused("#81 is not an open container"), stdin=PIPED_BODY
    ),
    "ITEM-29-not-a-container": Row(
        (*NEW, "--parent", str(LOOK_ALIKE)),
        refused(f"#{LOOK_ALIKE} is not a container"),
        stdin=PIPED_BODY,
    ),
    "ITEM-31": Row(
        (*NEW, "--origin", "gitlab#5"),
        refused('--origin needs storage = "state-ref"'),
        stdin=PIPED_BODY,
    ),
    "ITEM-34": Row(
        NEW,
        refused(
            "created #900 but GitHub did not set its type Task; set that type on the forge by hand"
        ),
        stdin=PIPED_BODY,
        forge_flags=("drop_created_issue_type",),
        writes=True,
    ),
    "ITEM-10": Row(("item", "show", "999"), refused(f"#999 does not exist in {REPOSITORY}")),
    "ITEM-63": Row(
        ("item", "edit", str(EDITED_ITEM), "--base", CURRENT_BASE),
        refused(
            f"item edit #{EDITED_ITEM} needs the new body on stdin: "
            f"aco item edit {EDITED_ITEM} --base <hash> < body.md"
        ),
    ),
    "ITEM-73": Row(
        ("item", "edit", str(EDITED_ITEM)),
        refused(
            f"item edit #{EDITED_ITEM} needs --base <hash>; "
            f"aco item show {EDITED_ITEM} --json prints it"
        ),
        stdin=REPLACEMENT,
    ),
    "ITEM-71": Row(
        ("item", "edit", str(EDITED_ITEM), "--base", CURRENT_BASE),
        stdout=f"EDITED #{EDITED_ITEM}\n",
        status=0,
        stdin=REPLACEMENT,
        writes=True,
    ),
    "ITEM-75": Row(
        ("item", "edit", str(EDITED_ITEM), "--base", CURRENT_BASE),
        stdout=f"UNCHANGED #{EDITED_ITEM}\n",
        status=0,
        stdin=STORED,
    ),
    "ITEM-22": Row(
        (*EDIT_TASK, *TWICE), stdout=f"EDITED #{TASK_ITEM} size=S\n", status=0, writes=True
    ),
    "ITEM-24": Row(
        (*EDIT_TASK, "--whole", "one PR"),
        stdout=f"EDITED #{TASK_ITEM} whole=one PR\n",
        status=0,
        writes=True,
    ),
    "ITEM-47": Row(
        (*EDIT_TASK, "--kind", "container"),
        stdout=f"EDITED #{TASK_ITEM} kind=container\n",
        status=0,
        writes=True,
    ),
    "ITEM-64": Row(
        (*EDIT_CHILD, *TWICE),
        stdout=f"UNCHANGED {CHILD_ID} size=S\n",
        status=0,
        first=(*EDIT_CHILD, *TWICE),
        world=World.STATE_REF,
    ),
    "ITEM-48": Row(
        ("item", "edit", PARENT_ID, "--kind", "task"),
        refused(f"{PARENT_ID} has an open child; a container with open children stays a container"),
        world=World.STATE_REF,
    ),
    "ITEM-41": Row(
        ("item", "edit", MALFORMED_ID, "--base", CURRENT_BASE),
        refused(
            f'a repair records state = "open"; close {MALFORMED_ID} afterwards '
            f"with aco item close {MALFORMED_ID}"
        ),
        stdin=state_ref_body("Repaired.", state="closed", closed_at="2026-09-20T00:00:00Z"),
        world=World.STATE_REF,
        malformed_item=True,
    ),
    "ITEM-52": Row(
        ("item", "new", "--title", "Fresh\udcfftwo"),
        refused(
            "body malformed: item: item file is not valid UTF-8; "
            "stored, that body would not read back, so nothing was written"
        ),
        stdin="",
        world=World.STATE_REF,
    ),
}


@pytest.fixture
def row(request: pytest.FixtureRequest) -> Row:
    """The table row this case runs; the fixtures that arrange its checkout read it."""
    return request.param


@pytest.fixture(autouse=True)
def commit_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def github_items(monkeypatch: pytest.MonkeyPatch, row: Row, github_world: Path) -> Written:
    """A GitHub-hosted board holding container `79`, the look-alike `951`, the open Task `484`
    and the item `72` whose body is `STORED`; the forge is the fake the command meets."""
    client = FakeForge(
        board_issues=(
            container_issue(CONTAINER, MINIMAL_BLOCK_TOML),
            board_issue(LOOK_ALIKE, "Ship it now", complete_contract("Ship it.")),
            board_issue(TASK_ITEM, "Task about to hold slices", STORED, kind=body.ItemKind.TASK),
        ),
        issue_references={
            EDITED_ITEM: forge.ItemReference(forge.ItemState.OPEN, "Claims", STORED),
            TASK_ITEM: forge.ItemReference(
                forge.ItemState.OPEN, "Task about to hold slices", STORED
            ),
            999: forge.ItemReference(forge.ItemState.MISSING),
        },
    )
    for flag in row.forge_flags:
        setattr(client, flag, True)
    serve_forge(monkeypatch, client)

    def written() -> object:
        return (
            tuple(client.created_issues),
            tuple(client.body_writes),
            tuple(client.retyped_items),
            tuple(client.item_bodies.items()),
        )

    return written


@pytest.fixture
def state_ref_items(
    monkeypatch: pytest.MonkeyPatch,
    row: Row,
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
) -> Written:
    """A `storage = "state-ref"` checkout over `bare_remote`, with no `gh` on `PATH`, holding a
    container with one open child, and an item that holds no block when the row names one."""
    items = {
        f"{PARENT_ID}.md": state_ref_body("Parent.", kind="container").encode(),
        f"{CHILD_ID}.md": state_ref_body("Child.", parent=PARENT_ID).encode(),
    }
    if row.malformed_item:
        items[f"{MALFORMED_ID}.md"] = NO_BLOCK
    seed_state_ref_checkout(monkeypatch, tmp_path, bare_remote, worktree, items)

    def written() -> object:
        return store.fetch_state(worktree=worktree, remote=f"file://{bare_remote}").tip

    return written


@pytest.mark.parametrize(
    "row", [pytest.param(row, id=name) for name, row in ROWS.items()], indirect=True
)
def test_the_command_prints_the_sentence_of_each_row(
    row: Row,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written = request.getfixturevalue(row.world)
    if row.first is not None:
        run_cli(list(row.first), capsys)
    arguments = with_current_base(list(row.arguments), capsys)
    before = written()

    if row.stdin is None:
        with devnull_on_stdin(tmp_path) as stdin:
            monkeypatch.setattr("sys.stdin", stdin)
            result = run_cli(arguments, capsys)
    else:
        result = run_cli(arguments, capsys, stdin=row.stdin)

    assert (result.status, result.stdout, result.stderr) == (row.status, row.stdout, row.stderr)
    assert (written() != before) == row.writes
