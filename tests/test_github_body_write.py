import json

import pytest

from aco import forge, github, github_body_write, github_graphql
from aco.github import GitHubForge
from aco.protocol import ClaimError


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        pytest.param(forge.ForgePermissionDeniedError("HTTP 403"), "REFUSED", id="W1-permission"),
        pytest.param(forge.ForgeNotFoundError("HTTP 404"), "REFUSED", id="W3-not-found"),
        pytest.param(
            ClaimError("gh is required for issue claims"), "REFUSED", id="W4-gh-never-ran"
        ),
        pytest.param(forge.ForgeTransientError("timeout"), "UNKNOWN", id="W5-transient"),
        pytest.param(
            forge.ForgeMalformedResponseError("not json"), "UNKNOWN", id="W7-malformed-response"
        ),
        pytest.param(forge.ForgeError("HTTP 500"), "UNKNOWN", id="W8-unclassified"),
    ],
)
def test_a_failed_body_write_is_refused_only_when_nothing_was_written(
    error: ClaimError, outcome: str
) -> None:
    """Spec: ADOPT-24, ADOPT-25 -- a refusal the forge gave before writing, or a `gh` that
    never ran, wrote nothing; every other failure may have written."""
    assert (
        github_body_write.body_write_outcome(error) is github_body_write.BodyWriteOutcome[outcome]
    )


def _revision(
    text: str | None,
    *,
    editor: str | None = "ada",
    newer: bool = False,
    deleted: bool = False,
    edited_at: str | None = None,
) -> dict[str, object]:
    """One revision node as GitHub answers it; `newer` gives it the later of two times."""
    return {
        "diff": text,
        "editedAt": edited_at or ("2026-11-08T10:05:00Z" if newer else "2026-11-08T10:00:00Z"),
        "deletedAt": "2026-11-08T10:06:00Z" if deleted else None,
        "editor": None if editor is None else {"login": editor},
    }


def _revisions(*nodes: dict[str, object]) -> tuple[github_graphql.BodyRevision, ...]:
    """The nodes parsed as the adapter parses the history read."""
    return github_graphql.EDIT_HISTORY_READ.parse_node({"userContentEdits": {"nodes": list(nodes)}})


class _GitHub:
    """A `gh` that answers the PATCH with `patch_answer` and the history read with `nodes`;
    either may be an error to raise instead."""

    def __init__(self, patch_answer: str | ClaimError, nodes: object) -> None:
        self.patch_answer = patch_answer
        self.nodes = nodes
        self.patches: list[tuple[list[str], bytes | None]] = []
        self.history_reads = 0

    def run(self, arguments: list[str], *, input_data: bytes | None = None) -> str:
        if "graphql" in arguments:
            self.history_reads += 1
            if isinstance(self.nodes, ClaimError):
                raise self.nodes
            return json.dumps({"n0": {"userContentEdits": {"nodes": self.nodes}}})
        self.patches.append((arguments, input_data))
        if isinstance(self.patch_answer, ClaimError):
            raise self.patch_answer
        return self.patch_answer

    def write(self, body: str = "new", *, replacing: str = "old") -> None:
        repository = github.repository_id("octo/demo")
        GitHubForge(repository, run=self.run).update_item_body(79, body, replacing=replacing)


def _written(body: str | None = "new") -> str:
    return json.dumps({"body": body})


def _answered(gh: _GitHub, *, replacing: str = "old") -> str | None:
    """The sentence the write raises, or `None` when it passes."""
    try:
        gh.write(replacing=replacing)
    except forge.ForgeBodyWrittenError as answer:
        return str(answer)
    return None


_UNKNOWN_HISTORY = "GitHub returned a malformed batched edit history"


@pytest.mark.parametrize(
    ("nodes", "replacing", "sentence"),
    [
        pytest.param(
            [_revision("new", newer=True), _revision("old")], "old", None, id="written-cleanly"
        ),
        pytest.param(
            [_revision("new", newer=True), _revision("hand edit", editor="ghost")],
            "old",
            "#79 body written over a change by ghost at 2026-11-08T10:00:00Z aco had not read; "
            "that change is only in the edit history",
            id="written-over-a-change-is-kept",
        ),
        pytest.param(
            [_revision("hand edit", editor="ghost", newer=True), _revision("new")],
            "old",
            "#79 body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
            id="overwritten-is-lost",
        ),
        pytest.param(
            [_revision("hand edit", editor=None, newer=True), _revision("new")],
            "old",
            "#79 body written, but overwritten in the meantime by an unknown editor "
            "at 2026-11-08T10:05:00Z",
            id="overwritten-by-an-unnamed-editor",
        ),
        pytest.param(
            [_revision("other", newer=True), _revision("hand edit")],
            "old",
            "#79 body written, not verified (the edit history does not show this write)",
            id="response-in-neither-revision",
        ),
        pytest.param(
            [_revision("new")],
            "old",
            "#79 body written, not verified (the edit history holds fewer than two revisions)",
            id="one-revision",
        ),
        pytest.param(
            [],
            "old",
            "#79 body written, not verified (the edit history holds fewer than two revisions)",
            id="no-revision",
        ),
        pytest.param(
            [_revision("new", newer=True), _revision("old", deleted=True)],
            "old",
            "#79 body written, not verified (a revision in the edit history was deleted)",
            id="deleted-revision",
        ),
    ],
)
def test_the_judgement_says_what_the_newest_two_revisions_show_of_the_write(
    nodes: list[dict[str, object]], replacing: str, sentence: str | None
) -> None:
    """The compare is pure: it says what the history shows of this write, and nothing it
    cannot show."""
    judgement = github_body_write.judge_write(79, "new", replacing, _revisions(*nodes))

    assert (None if judgement is None else str(judgement)) == sentence


@pytest.mark.parametrize(
    ("patch_answer", "nodes", "sentence"),
    [
        pytest.param(
            _written(),
            [_revision("new", newer=True), _revision("old")],
            None,
            id="written-cleanly",
        ),
        pytest.param(
            _written(None),
            [_revision(None, newer=True), _revision("old")],
            None,
            id="null-body-reads-as-empty",
        ),
        pytest.param(
            _written(),
            [_revision("hand edit", editor="ghost", newer=True), _revision("new")],
            "#79 body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
            id="overwritten",
        ),
        pytest.param(
            _written(),
            [_revision("new", edited_at="yesterday"), _revision("old")],
            f"#79 body written, not verified ({_UNKNOWN_HISTORY})",
            id="bad-edited-at",
        ),
        pytest.param(
            _written(),
            [_revision("new", edited_at="2026-99-99T99:99:99Z"), _revision("old")],
            f"#79 body written, not verified ({_UNKNOWN_HISTORY})",
            id="impossible-edited-at",
        ),
        pytest.param(
            _written(),
            forge.ForgeTransientError("timeout"),
            "#79 body written, not verified (timeout)",
            id="history-read-fails",
        ),
        pytest.param(
            _written(),
            ClaimError("gh is required for issue claims"),
            "#79 body written, not verified (gh is required for issue claims)",
            id="history-read-never-starts",
        ),
    ],
)
def test_the_adapter_reads_the_history_once_after_one_patch(
    patch_answer: str, nodes: object, sentence: str | None
) -> None:
    gh = _GitHub(patch_answer, nodes)

    answer = _answered(gh)

    assert (answer, len(gh.patches), gh.history_reads) == (sentence, 1, 1)


def test_a_history_failure_shows_foreign_text_as_one_bounded_printable_line() -> None:
    gh = _GitHub(_written(), ClaimError("first line\nsecond \x1b[2J" + "x" * 300))

    answer = _answered(gh)

    assert answer is not None
    assert "\n" not in answer
    assert "\x1b" not in answer
    assert answer.startswith("#79 body written, not verified (first line\\nsecond \\x1b[2J")
    assert answer.endswith("…)")
    assert len(answer) < 130


def test_a_failed_patch_is_not_followed_by_a_history_read() -> None:
    gh = _GitHub(forge.ForgePermissionDeniedError("HTTP 403"), [])
    write = gh.write

    with pytest.raises(forge.ForgePermissionDeniedError, match="HTTP 403"):
        write()

    assert gh.history_reads == 0


def test_the_write_patches_the_item_with_the_body_as_json() -> None:
    gh = _GitHub(_written(), [_revision("new", newer=True), _revision("old")])

    gh.write()

    assert gh.patches == [
        (
            ["api", "--method", "PATCH", "repos/octo/demo/issues/79", "--input", "-"],
            json.dumps({"body": "new"}).encode("utf-8"),
        )
    ]


@pytest.mark.parametrize(
    ("patch_answer", "cause"),
    [
        pytest.param(
            json.dumps({"state": "open"}),
            "GitHub returned a malformed body write answer",
            id="no-body",
        ),
        pytest.param("not json", "GitHub returned invalid body write answer JSON", id="not-json"),
        pytest.param(
            json.dumps({"body": 5}),
            "GitHub returned a malformed body write answer",
            id="body-not-text",
        ),
    ],
)
def test_a_patch_answer_without_a_readable_body_is_not_verified_and_reads_no_history(
    patch_answer: str, cause: str
) -> None:
    gh = _GitHub(patch_answer, [_revision("new", newer=True), _revision("old")])

    answer = _answered(gh)

    assert (answer, gh.history_reads) == (f"#79 body written, not verified ({cause})", 0)


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param("not a list", id="nodes-not-a-list"),
        pytest.param([5, _revision("old")], id="revision-not-an-object"),
        pytest.param([{**_revision("new"), "diff": 5}, _revision("old")], id="text-not-a-string"),
        pytest.param(
            [{**_revision("new"), "editor": {"login": 5}}, _revision("old")], id="login-not-text"
        ),
        pytest.param([{**_revision("new"), "editedAt": None}, _revision("old")], id="no-time"),
    ],
)
def test_a_malformed_edit_history_is_not_verified(nodes: object) -> None:
    gh = _GitHub(_written(), nodes)

    answer = _answered(gh)

    assert answer == (
        "#79 body written, not verified (GitHub returned a malformed batched edit history)"
    )
