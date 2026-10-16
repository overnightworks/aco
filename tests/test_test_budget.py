"""Behavioral tests for the spec-coverage ratchet in `scripts/test_budget.py`.

Each case measures two real test trees under `tmp_path` -- the merge-base's and the
change's -- and compares them the way `--ci` does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from script_fixtures import load_script

# test_budget imports its sibling script by name, so that script is registered first.
load_script("test_inventory")
test_budget = load_script("test_budget")


def _tree_citing(root: Path, *spec_ids: str) -> Path:
    citation = f'    """Spec: {", ".join(spec_ids)}."""\n' if spec_ids else ""
    module = root / "tests" / "test_example.py"
    module.parent.mkdir(parents=True)
    module.write_text(f"def test_example():\n{citation}    assert value == 1\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("base_ids", "head_ids", "expected_count", "expected_blocks"),
    [
        (("BOOT-01", "BOOT-02"), ("BOOT-01", "BOOT-02"), 2, False),
        (("BOOT-01",), ("BOOT-01", "BOOT-02"), 2, False),
        (("BOOT-01", "BOOT-02"), ("BOOT-01",), 1, True),
        (("BOOT-01",), ("BOOT-01", "BOOT-01"), 1, False),
        (("BOOT-01",), (), 0, True),
    ],
    ids=[
        "unchanged-citations-pass",
        "more-citations-pass",
        "fewer-citations-fail",
        "a-repeated-citation-counts-once",
        "dropping-every-citation-fails",
    ],
)
def test_the_tree_may_not_cite_fewer_spec_ids_than_the_merge_base(
    tmp_path: Path,
    base_ids: tuple[str, ...],
    head_ids: tuple[str, ...],
    expected_count: int,
    expected_blocks: bool,
) -> None:
    head = test_budget.measure(_tree_citing(tmp_path / "head", *head_ids))
    base = test_budget.measure(_tree_citing(tmp_path / "base", *base_ids))

    findings = test_budget.compare(head, base)

    assert (head["tests"].spec_ids, test_budget.blocks(findings, [])) == (
        expected_count,
        expected_blocks,
    )
