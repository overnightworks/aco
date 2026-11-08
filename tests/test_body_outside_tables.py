"""`aco check -` refuses a block table header outside the aco block (BODY-109)."""

import pytest
from cli_fixtures import run_cli

from aco import body

BLOCK = '```aco\nversion = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n```\n'
OUTSIDE = "is outside the aco block"


def refusal(header: str, line: int) -> str:
    return f"body malformed: aco: {header} on line {line} {OUTSIDE}\n"


@pytest.mark.usefixtures("clone")
class TestBlockTableHeaderOutsideTheBlock:
    @pytest.mark.parametrize(
        ("raw_body", "expected_stderr"),
        [
            pytest.param(
                BLOCK + "\n[[expectation]]\ntext = 'Q'\n",
                refusal("[[expectation]]", 8),
                id="expectation",
            ),
            pytest.param(
                BLOCK + "\n[[expectation.option]]\n",
                refusal("[[expectation.option]]", 8),
                id="option",
            ),
            pytest.param(BLOCK + "\n[[slice]]\n", refusal("[[slice]]", 8), id="slice"),
            pytest.param(BLOCK + "\n[record]\n", refusal("[record]", 8), id="record"),
            pytest.param(BLOCK + "\n [[slice]]\n", refusal("[[slice]]", 8), id="one-leading-space"),
            pytest.param(
                BLOCK + "\n   [[slice]]\n", refusal("[[slice]]", 8), id="three-leading-spaces"
            ),
            pytest.param(
                BLOCK + "\n[[ expectation.option ]]\n",
                refusal("[[ expectation.option ]]", 8),
                id="space-inside-brackets",
            ),
            pytest.param(
                BLOCK + "\n[record]  # lost\n", refusal("[record]", 8), id="trailing-comment"
            ),
            pytest.param(BLOCK + "\n[[slice]]   \n", refusal("[[slice]]", 8), id="trailing-space"),
            pytest.param(
                "Prose.\n\n" + BLOCK + "\n[[slice]]\n\n[record]\n",
                refusal("[[slice]]", 10) + refusal("[record]", 12),
                id="several-in-body-order",
            ),
            pytest.param(
                BLOCK.replace("\n", "\r\n") + "\r\n[[slice]]\r\n",
                refusal("[[slice]]", 8),
                id="crlf-body",
            ),
        ],
    )
    def test_each_header_outside_the_block_is_refused_with_its_line(
        self, capsys: pytest.CaptureFixture[str], raw_body: str, expected_stderr: str
    ) -> None:
        """Spec: BODY-109."""
        result = run_cli(["check", "-"], capsys, stdin=raw_body)
        assert (result.status, result.stdout, result.stderr) == (2, "", expected_stderr)

    @pytest.mark.parametrize(
        "raw_body",
        [
            pytest.param(BLOCK + "\n    [[slice]]\n", id="four-leading-spaces"),
            pytest.param(BLOCK + "\n```toml\n[[expectation]]\n```\n", id="quoted-fence"),
            pytest.param(BLOCK + "\n~~~\n[record]\n~~~\n", id="quoted-tilde-fence"),
            pytest.param(BLOCK + "\n[[slices]]\n[other]\n", id="another-table"),
            pytest.param(BLOCK + "\nText [record] here\n", id="header-inside-a-sentence"),
        ],
    )
    def test_a_line_that_is_no_block_header_outside_a_fence_passes(
        self, capsys: pytest.CaptureFixture[str], raw_body: str
    ) -> None:
        """Spec: BODY-06, BODY-109."""
        result = run_cli(["check", "-"], capsys, stdin=raw_body)
        assert (result.status, result.stdout, result.stderr) == (0, "body ok\n", "")

    @pytest.mark.parametrize(
        ("raw_body", "expected_stderr"),
        [
            pytest.param("[[slice]]\n", "body malformed: aco: no aco block\n", id="no-block"),
            pytest.param(
                BLOCK + "```aco\n```\n\n[[slice]]\n",
                "body malformed: aco: multiple aco blocks; exactly one is allowed\n",
                id="two-blocks",
            ),
            pytest.param(
                "```aco\nversion = \n```\n\n[[slice]]\n",
                "body malformed: aco: aco block is not valid TOML: "
                "Invalid value (at line 1, column 11)\n",
                id="not-toml",
            ),
            pytest.param(
                "```aco\nversion = 1\n\n[[slice]]\n",
                "body malformed: aco: unclosed aco block\n",
                id="unclosed",
            ),
        ],
    )
    def test_the_fence_defects_print_before_and_instead_of_the_outside_header(
        self, capsys: pytest.CaptureFixture[str], raw_body: str, expected_stderr: str
    ) -> None:
        """Spec: BODY-01..BODY-04, BODY-109."""
        result = run_cli(["check", "-"], capsys, stdin=raw_body)
        assert (result.status, result.stdout, result.stderr) == (2, "", expected_stderr)

    def test_the_outside_header_is_the_only_defect_printed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-109; the schema checks do not run beside it."""
        raw_body = '```aco\nversion = 1\nnext = "X"\n```\n\n[[slice]]\n'
        result = run_cli(["check", "-"], capsys, stdin=raw_body)
        assert (result.status, result.stderr) == (2, refusal("[[slice]]", 6))


def test_a_state_ref_record_title_still_reads_beside_a_header_outside_the_block() -> None:
    """Spec: BODY-109; the record read does not refuse."""
    raw_body = '```aco\nversion = 1\n\n[record]\ntitle = "Kept title"\n```\n\n[[expectation]]\n'
    assert body.readable_record_title(raw_body) == "Kept title"
