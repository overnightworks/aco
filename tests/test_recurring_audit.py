"""The recurring audit's due rule and anchor line, the rows of the item's table."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from aco import recurring_audit, workboard
from aco.protocol import ClaimError
from aco.recurring_audit import Reason

TODAY = date(2026, 11, 20)
ANCHOR_SHA = "a" * 40
ENTRY = recurring_audit.RecurringAudit(
    name="scenario", label="audit-scenario", landings=3, days=7, run="run it"
)


@dataclass(frozen=True)
class FakeLanding:
    sha: str
    committed_at: datetime


@dataclass(frozen=True)
class FakeIssue:
    number: int
    body: str


def trunk_with_anchor(*, landings_after: int, anchor_age_days: int) -> tuple[FakeLanding, ...]:
    """The first-parent landings oldest first: the anchor's commit, then `landings_after`."""
    anchor_day = datetime(2026, 11, 20, 12, tzinfo=UTC) - timedelta(days=anchor_age_days)
    anchor = FakeLanding(ANCHOR_SHA, anchor_day)
    later = tuple(FakeLanding(f"{index:040x}", anchor_day) for index in range(landings_after))
    return (FakeLanding("f" * 40, anchor_day), anchor, *later)


@dataclass(frozen=True)
class Scenario:
    anchor_text: str | None
    landings_after: int
    anchor_age_days: int
    reason: Reason | None
    landings_since: int | None
    days_since: int | None


SCENARIOS = {
    "landings reached": Scenario(ANCHOR_SHA, 3, 0, Reason.LANDINGS, 3, 0),
    "landings win over days": Scenario(ANCHOR_SHA, 5, 30, Reason.LANDINGS, 5, 30),
    "days passed with one landing": Scenario(ANCHOR_SHA, 1, 7, Reason.DAYS, 1, 7),
    "days passed with two landings": Scenario(ANCHOR_SHA, 2, 20, Reason.DAYS, 2, 20),
    "days not yet passed": Scenario(ANCHOR_SHA, 2, 6, None, 2, 6),
    "days passed without a landing": Scenario(ANCHOR_SHA, 0, 30, None, 0, 30),
    "no landing and no days": Scenario(ANCHOR_SHA, 0, 0, None, 0, 0),
    "no anchor": Scenario(None, 0, 0, Reason.NO_ANCHOR, None, None),
    "anchor names no full commit": Scenario("abc1234", 9, 9, Reason.ANCHOR_MALFORMED, None, None),
    "anchor commit off the trunk": Scenario("b" * 40, 9, 9, Reason.ANCHOR_OFF_TRUNK, None, None),
}


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_verdict_follows_the_tables_rows(scenario: Scenario) -> None:
    trunk = trunk_with_anchor(
        landings_after=scenario.landings_after, anchor_age_days=scenario.anchor_age_days
    )
    anchor = (
        None
        if scenario.anchor_text is None
        else recurring_audit.Anchor(issue=4, named=scenario.anchor_text)
    )

    found = recurring_audit.verdict(ENTRY, anchor, trunk, TODAY)

    actual = None if found is None else (found.reason, found.landings_since, found.days_since)
    expected = (
        None
        if scenario.reason is None
        else (scenario.reason, scenario.landings_since, scenario.days_since)
    )
    assert actual == expected


@pytest.mark.parametrize(
    ("named", "in_trunk", "expected"),
    [
        (ANCHOR_SHA, True, False),
        ("b" * 40, True, True),
        ("abc1234", True, False),
    ],
    ids=["on the trunk", "off the trunk", "malformed is not off the trunk"],
)
def test_off_trunk_asks_only_for_a_full_commit_missing_from_the_walk(
    named: str, in_trunk: bool, expected: bool
) -> None:
    trunk = trunk_with_anchor(landings_after=1, anchor_age_days=1) if in_trunk else ()

    actual = recurring_audit.is_off_trunk(recurring_audit.Anchor(issue=4, named=named), trunk)

    assert actual is expected


@dataclass(frozen=True)
class AnchorScenario:
    bodies: tuple[str, ...]
    expected: tuple[int, str] | None


ANCHOR_SCENARIOS = {
    "plain line": AnchorScenario((f"audited through {ANCHOR_SHA}",), (1, ANCHOR_SHA)),
    "newest issue with a line wins": AnchorScenario(
        ("no line here", f"audited through {ANCHOR_SHA}", "audited through " + "c" * 40),
        (2, ANCHOR_SHA),
    ),
    "last line of one issue wins": AnchorScenario(
        (f"audited through {'c' * 40}\naudited through {ANCHOR_SHA}\n",), (1, ANCHOR_SHA)
    ),
    "line inside a code fence counts": AnchorScenario(
        (f"```\naudited through {ANCHOR_SHA}\n```",), (1, ANCHOR_SHA)
    ),
    "surrounding space is stripped": AnchorScenario(
        (f"text\n   audited through   {ANCHOR_SHA}  \n",), (1, ANCHOR_SHA)
    ),
    "quoted line does not count": AnchorScenario((f"> audited through {ANCHOR_SHA}",), None),
    "line inside prose does not count": AnchorScenario(
        (f"we audited through {ANCHOR_SHA} yesterday",), None
    ),
    "no issue": AnchorScenario((), None),
    "rest that is no commit is kept for the verdict": AnchorScenario(
        ("audited through main",), (1, "main")
    ),
}


@pytest.mark.parametrize("scenario", ANCHOR_SCENARIOS.values(), ids=ANCHOR_SCENARIOS.keys())
def test_anchor_is_the_newest_issues_last_audited_through_line(scenario: AnchorScenario) -> None:
    issues = tuple(FakeIssue(number, body) for number, body in enumerate(scenario.bodies, start=1))

    found = recurring_audit.anchor_in(issues)

    actual = None if found is None else (found.issue, found.named)
    assert actual == scenario.expected


CONFIG_PATH = Path("/repo/.aco/board.toml")
VALID_ENTRY = 'name = "tests"\nlabel = "audit-tests"\nlandings = 50\ndays = 7\nrun = "run it"\n'


def entry_without(key: str) -> str:
    return "".join(line + "\n" for line in VALID_ENTRY.splitlines() if not line.startswith(key))


def entry_with(key: str, value: str) -> str:
    return entry_without(key) + f"{key} = {value}\n"


def test_configuration_without_an_audit_entry_has_none() -> None:
    """PIN-58: aco has no default entry."""
    assert workboard.parse_config("", CONFIG_PATH).audit == ()


def test_configuration_reads_every_entry_as_written() -> None:
    """PIN-58."""
    second = VALID_ENTRY.replace("tests", "other").replace("50", "9")

    parsed = workboard.parse_config(f"[[audit]]\n{VALID_ENTRY}[[audit]]\n{second}", CONFIG_PATH)

    assert [
        (entry.name, entry.label, entry.landings, entry.days, entry.run) for entry in parsed.audit
    ] == [
        ("tests", "audit-tests", 50, 7, "run it"),
        ("other", "audit-other", 9, 7, "run it"),
    ]


REFUSALS = {
    "PIN-58 a table": ("audit = {name = 'x'}\n", "audit must be an array of tables"),
    "PIN-58 plain values": ("audit = [1]\n", "audit must be an array of tables"),
    "PIN-59 unknown key": (
        f"[[audit]]\n{VALID_ENTRY}every = 3\n",
        "audit entry 1 has unknown key every",
    ),
    "PIN-59 unknown key escaped": (
        f'[[audit]]\n{VALID_ENTRY}"a\\u202eb" = 3\n',
        "audit entry 1 has unknown key a\\u202eb",
    ),
    "PIN-59 missing keys": (
        f"[[audit]]\n{entry_without('days')}",
        "audit entry 1 is missing days",
    ),
    "PIN-60 empty name": (
        f"[[audit]]\n{entry_with('name', '""')}",
        "audit entry 1 name must be a unique non-empty name",
    ),
    "PIN-60 padded name": (
        f"[[audit]]\n{entry_with('name', '" tests"')}",
        "audit entry 1 name must be a unique non-empty name",
    ),
    "PIN-60 name with a control": (
        f"[[audit]]\n{entry_with('name', '"te\\u001bsts"')}",
        "audit entry 1 name must be a unique non-empty name",
    ),
    "PIN-60 repeated name": (
        f"[[audit]]\n{VALID_ENTRY}[[audit]]\n{entry_with('label', '"audit-two"')}",
        "audit entry 2 name must be a unique non-empty name",
    ),
    "PIN-60 label with a comma": (
        f"[[audit]]\n{entry_with('label', '"a,b"')}",
        "audit entry 1 label must be a unique non-empty label without a comma",
    ),
    "PIN-60 padded label": (
        f"[[audit]]\n{entry_with('label', '"audit "')}",
        "audit entry 1 label must be a unique non-empty label without a comma",
    ),
    "PIN-60 repeated label": (
        f"[[audit]]\n{VALID_ENTRY}[[audit]]\n{entry_with('name', '"two"')}",
        "audit entry 2 label must be a unique non-empty label without a comma",
    ),
    "PIN-61 landings zero": (
        f"[[audit]]\n{entry_with('landings', '0')}",
        "audit entry 1 landings must be a positive integer up to 5000",
    ),
    "PIN-61 landings past the walk": (
        f"[[audit]]\n{entry_with('landings', '5001')}",
        "audit entry 1 landings must be a positive integer up to 5000",
    ),
    "PIN-61 landings bool": (
        f"[[audit]]\n{entry_with('landings', 'true')}",
        "audit entry 1 landings must be a positive integer up to 5000",
    ),
    "PIN-61 days negative": (
        f"[[audit]]\n{entry_with('days', '-1')}",
        "audit entry 1 days must be a positive integer",
    ),
    "PIN-61 days text": (
        f"[[audit]]\n{entry_with('days', '"7"')}",
        "audit entry 1 days must be a positive integer",
    ),
    "PIN-62 empty run": (
        f"[[audit]]\n{entry_with('run', '""')}",
        "audit entry 1 run must be non-empty text",
    ),
    "PIN-62 blank run": (
        f"[[audit]]\n{entry_with('run', '"  "')}",
        "audit entry 1 run must be non-empty text",
    ),
    "PIN-62 run is no text": (
        f"[[audit]]\n{entry_with('run', '3')}",
        "audit entry 1 run must be non-empty text",
    ),
}


@pytest.mark.parametrize(("text", "refusal"), REFUSALS.values(), ids=REFUSALS.keys())
def test_configuration_refuses_each_malformed_audit_entry(text: str, refusal: str) -> None:
    """PIN-58, PIN-59, PIN-60, PIN-61, PIN-62."""
    with pytest.raises(ClaimError) as refused:
        workboard.parse_config(text, CONFIG_PATH)

    assert str(refused.value) == f"board configuration {CONFIG_PATH} {refusal}"
