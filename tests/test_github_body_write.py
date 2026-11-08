import json

import pytest

from aco import forge, github, github_body_write
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


_REPOSITORY = github.repository_id("octo/demo")
_EARLIER = "2026-11-08T10:00:00Z"
_LATER = "2026-11-08T10:05:00Z"


def _node(text: str | None, *, editor: str | None = "ada", at: str = _EARLIER) -> dict[str, object]:
    return {
        "diff": text,
        "editedAt": at,
        "deletedAt": None,
        "editor": None if editor is None else {"login": editor},
    }


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
        GitHubForge(_REPOSITORY, run=self.run).update_item_body(79, body, replacing=replacing)


def _answered(gh: _GitHub, *, replacing: str = "old") -> str | None:
    """The sentence the write raises, or `None` when it passes."""
    try:
        gh.write(replacing=replacing)
    except forge.ForgeBodyWrittenError as answer:
        return str(answer)
    return None


_UNREAD_CHANGE = (
    "#79 body written over a change by ghost at 2026-11-08T10:00:00Z aco had not read; "
    "that change is only in the edit history"
)
_NOT_SHOWN = "#79 body written, not verified (the edit history does not show this write)"


@pytest.mark.parametrize(
    ("patch_answer", "nodes", "replacing", "sentence"),
    [
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("new", at=_LATER), _node("old")],
            "old",
            None,
            id="written-cleanly",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("new", at=_LATER), _node("hand edit", editor="ghost")],
            "old",
            _UNREAD_CHANGE,
            id="written-over-a-change-is-kept",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("hand edit", editor="ghost", at=_LATER), _node("new")],
            "old",
            "#79 body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
            id="overwritten-is-lost",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("hand edit", editor=None, at=_LATER), _node("new")],
            "old",
            "#79 body written, but overwritten in the meantime by an unknown editor "
            "at 2026-11-08T10:05:00Z",
            id="overwritten-by-an-unnamed-editor",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("other", at=_LATER), _node("hand edit")],
            "old",
            _NOT_SHOWN,
            id="response-in-neither-revision",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("new")],
            "old",
            "#79 body written, not verified (the edit history holds fewer than two revisions)",
            id="one-revision",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [],
            "old",
            "#79 body written, not verified (the edit history holds fewer than two revisions)",
            id="no-revision",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("new", at=_LATER), {**_node("old"), "deletedAt": _LATER}],
            "old",
            "#79 body written, not verified (a revision in the edit history was deleted)",
            id="deleted-revision",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            [_node("new", at="yesterday"), _node("old")],
            "old",
            "#79 body written, not verified (GitHub returned a malformed batched edit history)",
            id="bad-edited-at",
        ),
        pytest.param(
            json.dumps({"body": None}),
            [_node(None, at=_LATER), _node("")],
            "",
            None,
            id="null-reads-as-empty",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            forge.ForgeTransientError("timeout"),
            "old",
            "#79 body written, not verified (timeout)",
            id="history-read-fails",
        ),
        pytest.param(
            json.dumps({"body": "new"}),
            ClaimError("gh is required for issue claims"),
            "old",
            "#79 body written, not verified (gh is required for issue claims)",
            id="history-read-never-starts",
        ),
    ],
)
def test_a_body_write_is_checked_against_the_newest_two_revisions(
    patch_answer: str,
    nodes: list[dict[str, object]] | ClaimError,
    replacing: str,
    sentence: str | None,
) -> None:
    """The check says what the edit history shows of this write, and nothing it cannot show."""
    gh = _GitHub(patch_answer, nodes)

    answer = _answered(gh, replacing=replacing)

    assert (answer, len(gh.patches), gh.history_reads) == (sentence, 1, 1)


def test_a_failed_patch_is_not_followed_by_a_history_read() -> None:
    gh = _GitHub(forge.ForgePermissionDeniedError("HTTP 403"), [])
    write = gh.write

    with pytest.raises(forge.ForgePermissionDeniedError, match="HTTP 403"):
        write()

    assert gh.history_reads == 0


def test_the_write_patches_the_item_with_the_body_as_json() -> None:
    gh = _GitHub(json.dumps({"body": "new"}), [_node("new", at=_LATER), _node("old")])

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
    gh = _GitHub(patch_answer, [_node("new", at=_LATER), _node("old")])

    answer = _answered(gh)

    assert (answer, gh.history_reads) == (f"#79 body written, not verified ({cause})", 0)


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param("not a list", id="nodes-not-a-list"),
        pytest.param([5, _node("old")], id="revision-not-an-object"),
        pytest.param([{**_node("new"), "diff": 5}, _node("old")], id="text-not-a-string"),
        pytest.param([{**_node("new"), "editor": {"login": 5}}, _node("old")], id="login-not-text"),
        pytest.param([{**_node("new"), "editedAt": None}, _node("old")], id="no-time"),
    ],
)
def test_a_malformed_edit_history_is_not_verified(nodes: object) -> None:
    gh = _GitHub(json.dumps({"body": "new"}), nodes)

    answer = _answered(gh)

    assert answer == (
        "#79 body written, not verified (GitHub returned a malformed batched edit history)"
    )
