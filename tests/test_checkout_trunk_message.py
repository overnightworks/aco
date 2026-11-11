"""`checkout.trunk_landings` reads a landing's classification through git, also
when GitHub's merge queue appended its co-author paragraph after it. Every case
lands real commits on a real trunk."""

from pathlib import Path

import pytest
from cli_fixtures import push_repository_trunk, real_git, real_repository_with_bare_remote

from aco import checkout, workboard

TRUNK = "refs/remotes/hub/main"
NO_ITEM_FIX = workboard.NoItemClassification(workboard.NoItemKind.FIX)

ONE_FOREIGN_COMMIT = """Add b1 file (#4)

One commit without trailer.

No-Item: fix

Co-authored-by: Drive Author <drive@example.invalid>
"""
THREE_COMMITS_BY_ONE_AUTHOR = """Add b2 file (#6)

Three commits by one author.

No-Item: fix

---------

Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>
"""
TWO_COMMITS_BY_TWO_AUTHORS = """Add b3 file (#7)

Two commits by two authors.

No-Item: fix

---------

Co-authored-by: Alice Example <alice@example.invalid>
Co-authored-by: Carol Example <carol@example.invalid>
Co-authored-by: Bob Example <bob@example.invalid>
"""
THE_ENQUEUERS_OWN_COMMIT = """Add b1own file (#5)

One commit by the enqueuer identity.

No-Item: fix
"""
OTHER_TRAILING_TEXT = """Add b4 file (#8)

No-Item: fix

Thanks for the review.

Co-authored-by: Drive Author <drive@example.invalid>
"""
ANOTHER_LINE_IN_THE_COAUTHOR_PARAGRAPH = """Add b5 file (#9)

No-Item: fix

Co-authored-by: Drive Author <drive@example.invalid>
Reviewed by nobody.
"""
WORK_ITEM_AND_NO_ITEM = """Add b6 file (#10)

Work-Item: #20
No-Item: fix

---------

Co-authored-by: Drive Author <drive@example.invalid>
"""
TWO_WORK_ITEMS = """Add b7 file (#11)

Work-Item: #20
Work-Item: #21

Co-authored-by: Drive Author <drive@example.invalid>
"""
WORK_ITEM_IN_PROSE = """Add b8 file (#12)

See the Work-Item: #20 note, which is prose.

Co-authored-by: Drive Author <drive@example.invalid>
"""
LAST_PARAGRAPH_ALREADY_CLASSIFIED = """Add b9 file (#13)

Co-authored-by: Drive Author <drive@example.invalid>

No-Item: fix
"""
CARRIAGE_RETURN_INSIDE_A_VALUE = """Add b10 file (#14)

Work-Item: #12\r#13

Co-authored-by: Drive Author <drive@example.invalid>
"""
NO_BREAK_SPACE_ONLY_LINE = """Add b11 file (#15)

No-Item: fix
\u00a0

Co-authored-by: Drive Author <drive@example.invalid>
"""
EMPTY_WORK_ITEM_VALUE_BEFORE_A_VALUE = """Add b12 file (#16)

Body.

Work-Item:
Work-Item: #12

---------

Co-authored-by: Drive Author <drive@example.invalid>
"""
NO_BREAK_SPACE_BEFORE_A_VALUE = """Add b14 file (#18)

Work-Item: \N{NO-BREAK SPACE}#12

---------

Co-authored-by: Drive Author <drive@example.invalid>
"""


def landings_of(tmp_path: Path, message: bytes) -> tuple[checkout.TrunkLanding, ...]:
    """The landings of a trunk whose one commit carries exactly `message`: the commit
    object is written byte for byte, so no porcelain re-encodes or cleans it."""
    repository, _remote = real_repository_with_bare_remote(tmp_path, remote_name="hub")
    tree = real_git(repository, "write-tree").stdout.strip()
    header = f"tree {tree}\nauthor T <t@example.invalid> 1794331725 +0000\n"
    header += "committer T <t@example.invalid> 1794331725 +0000\n\n"
    commit_path = tmp_path / "commit"
    commit_path.write_bytes(header.encode() + message)
    commit = real_git(
        repository, "hash-object", "-t", "commit", "-w", "--literally", str(commit_path)
    )
    real_git(repository, "update-ref", "refs/heads/main", commit.stdout.strip())
    push_repository_trunk(repository, "hub")
    return checkout.trunk_landings(TRUNK, 20, directory=repository)


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        pytest.param(ONE_FOREIGN_COMMIT, NO_ITEM_FIX, id="one-foreign-commit"),
        pytest.param(THREE_COMMITS_BY_ONE_AUTHOR, NO_ITEM_FIX, id="three-commits-by-one-author"),
        pytest.param(TWO_COMMITS_BY_TWO_AUTHORS, NO_ITEM_FIX, id="two-commits-by-two-authors"),
        pytest.param(THE_ENQUEUERS_OWN_COMMIT, NO_ITEM_FIX, id="enqueuers-own-commit"),
        pytest.param(OTHER_TRAILING_TEXT, None, id="other-trailing-text"),
        pytest.param(
            ANOTHER_LINE_IN_THE_COAUTHOR_PARAGRAPH, None, id="another-line-in-the-paragraph"
        ),
        pytest.param(WORK_ITEM_IN_PROSE, None, id="classification-in-prose"),
        pytest.param(
            LAST_PARAGRAPH_ALREADY_CLASSIFIED, NO_ITEM_FIX, id="last-paragraph-already-classified"
        ),
        pytest.param(
            TWO_WORK_ITEMS, workboard.TrunkWorkItemClassification((20, 21)), id="work-items"
        ),
        pytest.param(
            EMPTY_WORK_ITEM_VALUE_BEFORE_A_VALUE,
            workboard.TrunkWorkItemClassification((12,)),
            id="empty-work-item-value-is-no-value-to-git",
        ),
        pytest.param(
            NO_BREAK_SPACE_BEFORE_A_VALUE,
            workboard.ClassificationDefect(
                "carries `Work-Item: \N{NO-BREAK SPACE}#12`; "
                "a trunk trailer names #n, aco-xxxxxx, or the bare number n"
            ),
            id="no-break-space-before-a-value-stays-refused",
        ),
        pytest.param(NO_BREAK_SPACE_ONLY_LINE, None, id="no-break-space-is-content-to-git"),
        pytest.param(
            CARRIAGE_RETURN_INSIDE_A_VALUE,
            workboard.ClassificationDefect(
                "carries `Work-Item: #12\r#13`; "
                "a trunk trailer names #n, aco-xxxxxx, or the bare number n"
            ),
            id="control-byte-in-a-value-stays-refused",
        ),
        pytest.param(
            WORK_ITEM_AND_NO_ITEM,
            workboard.ClassificationDefect(
                "carries both `Work-Item:` and `No-Item:` trailers; "
                "a landed commit is one or the other"
            ),
            id="contradictory-classification-stays-refused",
        ),
    ],
)
def test_a_landing_is_classified_through_git_past_the_merge_queues_coauthor_paragraph(
    tmp_path: Path,
    message: str,
    classification: workboard.TrunkClassification | workboard.ClassificationDefect | None,
) -> None:
    """Spec: LAND-83, LAND-84, LAND-60"""
    [landing] = landings_of(tmp_path, message.encode())

    assert landing.classification == classification


def test_a_message_that_is_not_utf8_leaves_the_trunk_readable(tmp_path: Path) -> None:
    """Spec: LAND-83"""
    message = "Caf\xe9 (#4)\n\nNo-Item: fix\n\nCo-authored-by: Ren\xe9 <rene@example.invalid>\n"

    [landing] = landings_of(tmp_path, message.encode("latin-1"))

    assert landing.classification == NO_ITEM_FIX
