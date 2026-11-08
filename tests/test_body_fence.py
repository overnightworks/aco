"""The one walk over a body's CommonMark fences."""

import pytest

from aco.body_fence import walk_fences

FenceShape = tuple[int, int | None, str, str]


def shape(body: str) -> tuple[list[FenceShape], list[tuple[int, str]]]:
    walk = walk_fences(body)
    fences = [(f.opening_line, f.closing_line, f.info, f.interior) for f in walk.fences]
    return fences, list(walk.outside_lines)


@pytest.mark.parametrize(
    ("body", "fences", "outside"),
    [
        pytest.param("", [], [], id="empty"),
        pytest.param("a\nb\n", [], [(0, "a"), (1, "b")], id="prose-only"),
        pytest.param(
            "a\n```aco\nx = 1\n```\nb\n",
            [(1, 3, "aco", "x = 1\n")],
            [(0, "a"), (4, "b")],
            id="one-fence",
        ),
        pytest.param(
            "````md\n```aco\nx\n```\n````\nz",
            [(0, 4, "md", "```aco\nx\n```\n")],
            [(5, "z")],
            id="nested-fence-stays-content",
        ),
        pytest.param(
            "~~~\n```\n~~~\n",
            [(0, 2, "", "```\n")],
            [],
            id="other-character-never-closes",
        ),
        pytest.param(
            "a\n```aco\nx = 1\n",
            [(1, None, "aco", "x = 1\n")],
            [(0, "a")],
            id="unclosed-runs-to-the-end",
        ),
        pytest.param(
            "```aco\n```python\n```\n",
            [(0, 2, "aco", "```python\n")],
            [],
            id="closing-with-info-string-is-content",
        ),
        pytest.param(
            "```aco  \n``` \t\n",
            [(0, 1, "aco", "")],
            [],
            id="info-and-closing-whitespace-trimmed",
        ),
        pytest.param(
            "    ```aco\n",
            [],
            [(0, "    ```aco")],
            id="four-spaces-is-no-fence",
        ),
        pytest.param(
            "```aco\r\nx = 1\r\n```\r\ny\r\n",
            [(0, 2, "aco", "x = 1\r\n")],
            [(3, "y")],
            id="crlf-interior-byte-exact",
        ),
        pytest.param(
            "a\x0bb\n```aco\nx\n```\n",
            [(2, 4, "aco", "x\n")],
            [(0, "a"), (1, "b")],
            id="vertical-tab-ends-a-line",
        ),
        pytest.param(
            "```aco\na\u2028```\n",
            [(0, 2, "aco", "a\u2028")],
            [],
            id="line-separator-ends-a-line-inside-a-fence",
        ),
    ],
)
def test_the_walk_reads_fences_and_the_lines_outside_them(
    body: str, fences: list[FenceShape], outside: list[tuple[int, str]]
) -> None:
    assert shape(body) == (fences, outside)
