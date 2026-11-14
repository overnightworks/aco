"""What `protocol.valid_scope` admits as a claim scope entry."""

import re

import pytest

from aco import protocol
from aco.protocol import InvalidClaimMarkerError


@pytest.mark.parametrize(
    ("scope", "match"),
    [
        pytest.param("src", "must be a non-empty list", id="not-a-list"),
        pytest.param([], "must be a non-empty list", id="empty-list"),
        pytest.param([5], "scope entries must be text", id="entry-not-text"),
        pytest.param([" src"], "canonical bounded paths", id="padded-entry"),
        pytest.param(
            [f"src/file{index}.py" for index in range(protocol.MAX_SCOPE_ENTRIES + 1)],
            "exceeds 256 entries",
            id="too-many-entries",
        ),
        pytest.param(["src\\widget.py"], "canonical bounded paths", id="backslash"),
        pytest.param(["src/\x1fwidget.py"], "canonical bounded paths", id="control-character"),
        pytest.param(["docs/\x9b2J.md"], "canonical bounded paths", id="c1-csi"),
        pytest.param(["docs/a\N{RIGHT-TO-LEFT OVERRIDE}b.md"], "canonical bounded paths", id="rlo"),
        pytest.param(["docs/a\N{LEFT-TO-RIGHT ISOLATE}b.md"], "canonical bounded paths", id="lri"),
        pytest.param(["docs/a\N{ZERO WIDTH SPACE}b.md"], "canonical bounded paths", id="zwsp"),
        pytest.param(["x" * (protocol.MAX_SCOPE_PATH_LENGTH + 1)], "canonical", id="overlong"),
        pytest.param(["/etc/passwd"], "must be repository-relative", id="absolute"),
        pytest.param(["../outside.py"], "must be repository-relative", id="escapes-upwards"),
        pytest.param(["~/secrets"], "must be repository-relative", id="home-relative"),
        pytest.param([".git/config"], "must be repository-relative", id="git-directory"),
        pytest.param(["./src"], "must be repository-relative", id="not-normalized"),
        pytest.param(
            ["frontend/**"], re.escape("not glob patterns: 'frontend/**'"), id="double-star"
        ),
        pytest.param(["src/*.py"], re.escape("not glob patterns: 'src/*.py'"), id="star"),
        pytest.param(["a?b"], re.escape("not glob patterns: 'a?b'"), id="question-mark"),
        pytest.param(["src", "src"], "duplicate paths", id="duplicate"),
    ],
)
def test_claim_scope_must_be_canonical_repository_relative_paths(scope: object, match: str) -> None:
    """`valid_scope` guards every path that reaches a claim -- `cmd_claim._request`,
    `cmd_rescope._rescope_scope_entries`'s add/drop, the `--path` lookup, and `claims_holding_path`
    all hand it operator-supplied text."""
    with pytest.raises(InvalidClaimMarkerError, match=match):
        protocol.valid_scope(scope)


def test_claim_scope_keeps_a_path_with_a_printable_space() -> None:
    """NBSP is text, not a display control, so a scope path carrying it stays a valid entry."""
    path = "docs/a\N{NO-BREAK SPACE}b.md"

    assert protocol.valid_scope([path]) == (path,)


def test_claim_scope_keeps_a_route_directory_named_with_square_brackets() -> None:
    """Only `*` and `?` make an entry a glob pattern; real paths use `[` and `]`."""
    path = "src/routes/[id]"

    assert protocol.valid_scope([path]) == (path,)
