"""What GitHub's merge queue appends to a landed commit message."""

import pytest

from aco.trunk_message import without_appended_coauthors

CLASSIFIED = "Add file (#4)\n\nBody.\n\nNo-Item: fix\n"
COAUTHORS = "Co-authored-by: Alice Example <alice@example.invalid>\n"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        pytest.param(f"{CLASSIFIED}\n{COAUTHORS}", CLASSIFIED, id="one-coauthor"),
        pytest.param(f"{CLASSIFIED}\n---------\n\n{COAUTHORS}", CLASSIFIED, id="hyphen-line"),
        pytest.param(
            f"{CLASSIFIED}\n---------\n\n{COAUTHORS}{COAUTHORS}", CLASSIFIED, id="two-coauthors"
        ),
        pytest.param(
            f"{CLASSIFIED}\n\n\n---------  \n \n{COAUTHORS}\n\n",
            CLASSIFIED,
            id="extra-blank-lines",
        ),
        pytest.param(
            f"{CLASSIFIED}\nCO-AUTHORED-BY: Bob <bob@example.invalid>\n",
            CLASSIFIED,
            id="key-case",
        ),
        pytest.param(
            f"{CLASSIFIED}\nThanks.\n\n{COAUTHORS}", f"{CLASSIFIED}\nThanks.\n", id="prose"
        ),
        pytest.param(
            f"{CLASSIFIED}{COAUTHORS}", None, id="coauthor-in-the-classification-paragraph"
        ),
        pytest.param(CLASSIFIED, None, id="no-appended-block"),
        pytest.param(f"{CLASSIFIED}\nThanks.\n", None, id="other-trailing-text"),
        pytest.param(
            f"{CLASSIFIED}\n{COAUTHORS}Thanks.\n", None, id="coauthor-paragraph-with-other-line"
        ),
        pytest.param(f"{CLASSIFIED}\nCo-authored-by:\n", None, id="coauthor-without-value"),
        pytest.param(f"{CLASSIFIED}\n---------\n", None, id="hyphens-only"),
        pytest.param(COAUTHORS, None, id="nothing-before-the-block"),
        pytest.param(f"\n---------\n\n{COAUTHORS}", None, id="only-hyphens-before-the-block"),
        pytest.param("", None, id="empty"),
    ],
)
def test_only_the_block_the_merge_queue_appends_is_cut_off(
    message: str, expected: str | None
) -> None:
    """Spec: LAND-83, LAND-84"""
    assert without_appended_coauthors(message) == expected
