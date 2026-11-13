"""The `Routing:` line a merge commit or an abandon reason carries, read into typed fields.

Every figure that does not parse is unknown (`None` or a missing stage), never a guess."""

import pytest

from aco.routing_line import RoutingLine, RoutingStage, parse_routing_line

STAGES = (
    "build sonnet-5.5/high; fix none; review opus-5.5/medium; "
    "test sonnet-5.5/medium; gate gpt-6-astra/high; land haiku-5.5/low"
)
PARSED_STAGES = (
    (RoutingStage.BUILD, "sonnet-5.5/high"),
    (RoutingStage.FIX, "none"),
    (RoutingStage.REVIEW, "opus-5.5/medium"),
    (RoutingStage.TEST, "sonnet-5.5/medium"),
    (RoutingStage.GATE, "gpt-6-astra/high"),
    (RoutingStage.LAND, "haiku-5.5/low"),
)


def read(
    line: str,
) -> tuple[tuple[tuple[RoutingStage, str], ...], int | None, int | None, str | None]:
    parsed = parse_routing_line(line)
    assert parsed is not None
    return fields_of(parsed)


def fields_of(
    parsed: RoutingLine,
) -> tuple[tuple[tuple[RoutingStage, str], ...], int | None, int | None, str | None]:
    return (
        tuple(sorted(parsed.stages.items(), key=lambda pair: list(RoutingStage).index(pair[0]))),
        parsed.fix_rounds,
        parsed.blocking,
        parsed.experiment,
    )


def test_a_full_routing_line_reads_every_field() -> None:
    """Spec: LANREC-11, LANREC-12, LANREC-16."""
    line = (
        f"Routing: {STAGES}. Fix rounds: 2. Experiment: builder-sonnet. "
        "Blocking: red CI → ci; a missing test → review"
    )

    assert read(line) == (PARSED_STAGES, 2, 2, "builder-sonnet")


def test_the_line_is_found_inside_a_longer_message() -> None:
    """Spec: LANREC-13."""
    message = (
        f"Merge pull request #5\n\nWhat changes.\n\nRouting: {STAGES}. "
        "Fix rounds: 0. Blocking: none\n\nWork-Item: #7\n"
    )

    assert read(message) == (PARSED_STAGES, 0, 0, None)


@pytest.mark.parametrize(
    ("message"),
    [
        pytest.param("Merge pull request #5\n\nWork-Item: #7\n", id="no-line"),
        pytest.param(f"Routing: {STAGES}.\nRouting: {STAGES}.\n", id="two-lines"),
        pytest.param(f"  Routing: {STAGES}.\n", id="indented-line"),
        pytest.param("", id="empty"),
    ],
)
def test_a_message_without_exactly_one_routing_line_has_no_routing(message: str) -> None:
    """Spec: LANREC-14."""
    assert parse_routing_line(message) is None


@pytest.mark.parametrize(
    ("line", "expected_rounds"),
    [
        pytest.param(
            "Routing: build a/b. Fix rounds: 3, hard: layout. Blocking: none", 3, id="hard"
        ),
        pytest.param("Routing: build a/b. Fix rounds: 12. Blocking: none", 12, id="two-digits"),
        pytest.param(
            "Routing: build a/b. Fix rounds: 1234. Blocking: none", None, id="four-digits"
        ),
        pytest.param("Routing: build a/b. Fix rounds: many. Blocking: none", None, id="word"),
        pytest.param("Routing: build a/b. Fix rounds: 1.5. Blocking: none", None, id="decimal"),
        pytest.param("Routing: build a/b. Fix rounds: 2x. Blocking: none", None, id="suffixed"),
        pytest.param("Routing: build a/b. Fix rounds: 2", 2, id="at-the-end-of-the-line"),
        pytest.param("Routing: build a/b. Blocking: none", None, id="absent"),
        pytest.param(
            "Routing: build a/b. Fix rounds: 1. Fix rounds: 2. Blocking: none",
            None,
            id="a-doubled-sentence",
        ),
    ],
)
def test_fix_rounds_are_a_short_whole_number_or_unknown(
    line: str, expected_rounds: int | None
) -> None:
    """Spec: LANREC-18, LANREC-23."""
    assert read(line)[1] == expected_rounds


@pytest.mark.parametrize(
    ("blocking", "expected_count"),
    [
        pytest.param("none", 0, id="none"),
        pytest.param("none.", 0, id="none-with-a-full-stop"),
        pytest.param("none. Blocking: a → ci; b → ci", None, id="none-then-findings"),
        pytest.param("none. The gate ran on another model.", None, id="none-then-a-sentence"),
        pytest.param("a → nowhere", 1, id="a-destination-that-is-no-stage"),
        pytest.param("one thing → ci", 1, id="one"),
        pytest.param("a → build; b, with a comma → review; c → head", 3, id="three"),
        pytest.param("a → head, scope (rescope)", 1, id="a-stage-then-a-comment"),
        pytest.param("a → ci. The gate ran on another model.", 1, id="a-sentence-after-the-last"),
        pytest.param("a → ci. Experiment: tagged", 1, id="an-experiment-sentence-after"),
        pytest.param("no arrow at all", None, id="no-arrow"),
        pytest.param("a → b → ci", None, id="two-arrows-in-one-finding"),
        pytest.param("a → ; b → ci", None, id="an-arrow-without-a-stage"),
        pytest.param("a (x; y) → ci", None, id="a-semicolon-inside-a-finding"),
        pytest.param("", None, id="empty"),
    ],
)
def test_the_blocking_count_is_one_per_arrow_or_unknown_when_ambiguous(
    blocking: str, expected_count: int | None
) -> None:
    """Spec: LANREC-19, LANREC-23, LANREC-24."""
    assert read(f"Routing: build a/b. Fix rounds: 0. Blocking: {blocking}")[2] == expected_count


@pytest.mark.parametrize(
    ("sentence", "expected_tag"),
    [
        pytest.param("Experiment: builder-haiku.", "builder-haiku", id="plain"),
        pytest.param("Experiment: a" + "b" * 39 + ".", "a" + "b" * 39, id="forty-characters"),
        pytest.param("Experiment: a" + "b" * 40 + ".", None, id="forty-one-characters"),
        pytest.param("Experiment: Builder.", None, id="uppercase"),
        pytest.param("Experiment: a_b.", None, id="underscore"),
        pytest.param("Experiment: trial two.", None, id="two-words"),
        pytest.param("Experiment: trial.two.", None, id="a-dot-inside-the-tag"),
        pytest.param("Experiment: a. Experiment: b.", None, id="a-doubled-sentence"),
        pytest.param("", None, id="absent"),
    ],
)
def test_the_experiment_tag_is_a_short_lowercase_token_or_unknown(
    sentence: str, expected_tag: str | None
) -> None:
    """Spec: LANREC-20, LANREC-23."""
    assert read(f"Routing: build a/b. Fix rounds: 0. {sentence} Blocking: none")[3] == expected_tag


@pytest.mark.parametrize(
    ("line", "expected_rounds", "expected_tag"),
    [
        pytest.param(
            "Routing: build a/b. Fix rounds: 1. Blocking: a → ci; Fix rounds: 9. Experiment: x",
            1,
            None,
            id="rounds-and-an-experiment-inside-a-finding",
        ),
        pytest.param(
            "Routing: build a/b. Blocking: a. Fix rounds: 9 → ci. Experiment: x",
            None,
            None,
            id="a-finding-that-looks-like-the-fields",
        ),
        pytest.param(
            "Routing: build a/b. Experiment: y. Blocking: none",
            None,
            "y",
            id="the-fields-before-blocking",
        ),
        pytest.param(
            "Routing: build a/b. Blocking: a → ci. Blocking: b → ci. Experiment: x",
            None,
            None,
            id="an-experiment-after-a-doubled-blocking",
        ),
        pytest.param(
            "Routing: build a/b. Blocking: a → ci. Blocking: b → ci. Fix rounds: 7",
            None,
            None,
            id="rounds-after-a-doubled-blocking",
        ),
        pytest.param(
            "Routing: build a/b. Experiment: y. Blocking: a → ci. Blocking: b → ci",
            None,
            "y",
            id="the-fields-before-a-doubled-blocking",
        ),
    ],
)
def test_the_rounds_and_the_experiment_are_never_read_from_a_finding(
    line: str, expected_rounds: int | None, expected_tag: str | None
) -> None:
    """Spec: LANREC-18, LANREC-20."""
    _, rounds, _, tag = read(line)

    assert (rounds, tag) == (expected_rounds, expected_tag)


@pytest.mark.parametrize(
    ("stages", "expected"),
    [
        pytest.param(
            "build a/b; fix none; review c/d",
            ((RoutingStage.BUILD, "a/b"), (RoutingStage.FIX, "none"), (RoutingStage.REVIEW, "c/d")),
            id="a-prefix-of-the-stages",
        ),
        pytest.param(
            "build Sonnet/High; fix none",
            ((RoutingStage.FIX, "none"),),
            id="a-stage-with-capitals-is-unknown",
        ),
        pytest.param(
            "build none; test none", ((RoutingStage.TEST, "none"),), id="build-has-no-none"
        ),
        pytest.param("build a/b; build c/d", (), id="a-stage-named-twice-is-unknown"),
        pytest.param("build a b; fix", (), id="no-model-and-effort"),
        pytest.param("review a/b; build c/d", (), id="two-stages-out-of-order"),
        pytest.param("build a/b; land c/d; fix none", (), id="the-last-stage-misplaced"),
        pytest.param("deploy a/b; land c/d", ((RoutingStage.LAND, "c/d"),), id="an-unknown-stage"),
    ],
)
def test_a_stage_that_does_not_fit_is_left_out_and_the_others_stay(
    stages: str, expected: tuple[tuple[RoutingStage, str], ...]
) -> None:
    """Spec: LANREC-16, LANREC-17, LANREC-23."""
    assert read(f"Routing: {stages}. Fix rounds: 0. Blocking: none")[0] == expected


def test_a_line_that_ends_after_its_stages_still_reads_them() -> None:
    """Spec: LANREC-16."""
    assert read("Routing: build a/b; land c/d")[0] == (
        (RoutingStage.BUILD, "a/b"),
        (RoutingStage.LAND, "c/d"),
    )


def test_a_line_with_nothing_readable_is_still_a_line() -> None:
    """Spec: LANREC-14, LANREC-21."""
    assert read("Routing: see the pull request") == ((), None, None, None)
