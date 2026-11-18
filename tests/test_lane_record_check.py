"""`aco lane-record check FILE` judges a lane record file read-only, and says why not."""

import json
from pathlib import Path
from typing import cast

import pytest
from cli_fixtures import run_cli
from lane_record_fixtures import lane_record_object

from aco import lane_record, report

MISSING = object()


def record_text_with(field: str, key: str, value: object) -> str:
    """The valid record with `field`'s member `key` set to `value`, or removed for `MISSING`."""
    record = lane_record_object()
    members = cast(dict[str, object], record[field])
    if value is MISSING:
        del members[key]
    else:
        members[key] = value
    return json.dumps(record)


def record_text_without(field: str) -> str:
    record = lane_record_object()
    del record[field]
    return json.dumps(record)


VALID_RECORDS = [
    pytest.param(json.dumps(lane_record_object()), id="every-field"),
    pytest.param(record_text_without("risk"), id="no-risk"),
    pytest.param(record_text_without("experiment"), id="no-experiment"),
    pytest.param(json.dumps(lane_record_object(verdicts=[])), id="no-verdict"),
    pytest.param(record_text_with("stages", "fix", "grok-4.6/high"), id="a-fix-stage-that-ran"),
    pytest.param(record_text_with("blocking", "ci", 999), id="the-largest-count"),
]

MALFORMED_RECORDS = [
    pytest.param("{", "not valid JSON", id="not-json"),
    pytest.param("[" * 100000, "not valid JSON", id="arrays-nested-past-the-parser-limit"),
    pytest.param('{"a":' * 100000, "not valid JSON", id="objects-nested-past-the-parser-limit"),
    pytest.param('{"version": 1, "version": 1}', "a key stated twice", id="a-key-stated-twice"),
    pytest.param("[]", "the record must be an object", id="not-an-object"),
    pytest.param(
        json.dumps(lane_record_object(version=2)),
        "version 2 is unknown; this aco reads version 1",
        id="an-unknown-version",
    ),
    pytest.param(
        json.dumps({**lane_record_object(version=2), "cost": 1}),
        "version 2 is unknown; this aco reads version 1",
        id="an-unknown-version-with-another-unknown-key",
    ),
    pytest.param(
        json.dumps(lane_record_object(version=True)),
        "version must be the whole number 1",
        id="a-boolean-version",
    ),
    pytest.param(
        '{"version": 1.0}', "version must be the whole number 1", id="a-fractional-version"
    ),
    pytest.param(
        json.dumps(lane_record_object(version="1")),
        "version must be the whole number 1",
        id="a-text-version",
    ),
    pytest.param(
        json.dumps(lane_record_object(version="v" * 70)),
        "version must be the whole number 1",
        id="a-long-text-version",
    ),
    pytest.param(
        '{"version": ' + "9" * 41 + "}",
        "version must be the whole number 1",
        id="a-version-too-long-to-show",
    ),
    pytest.param(
        '{"version": ' + "9" * 5000 + "}",
        "version must be the whole number 1",
        id="a-version-past-the-parser-digit-limit",
    ),
    pytest.param(
        "\ufeff" + json.dumps(lane_record_object()),
        "begins with a UTF-8 byte order mark; save it without one",
        id="a-byte-order-mark",
    ),
    pytest.param(
        record_text_without("version"), "the record lacks 'version'", id="no-version-stated"
    ),
    pytest.param(
        json.dumps(lane_record_object(cost=1)),
        "the record has an unknown key 'cost'",
        id="an-unknown-field",
    ),
    pytest.param(
        record_text_with("stages", "build", "sonnet 5/high"),
        "stage build must be <model>/<effort> or none",
        id="a-stage-with-whitespace",
    ),
    pytest.param(
        record_text_with("stages", "build", "none"),
        "stage build must be <model>/<effort> or none",
        id="a-build-stage-that-did-not-run",
    ),
    pytest.param(
        record_text_with("stages", "land", MISSING),
        "stages lacks 'land'",
        id="a-stage-not-stated",
    ),
    pytest.param(
        record_text_with("stages", "deploy", "a/b"),
        "stages has an unknown key 'deploy'",
        id="an-unknown-stage",
    ),
    pytest.param(
        record_text_with("fix_rounds", "ci", -1),
        "fix_rounds.ci must be a whole number from 0 to 999",
        id="a-negative-count",
    ),
    pytest.param(
        record_text_with("blocking", "gate", 1.5),
        "blocking.gate must be a whole number from 0 to 999",
        id="a-fractional-count",
    ),
    pytest.param(
        record_text_with("blocking", "test", True),
        "blocking.test must be a whole number from 0 to 999",
        id="a-boolean-count",
    ),
    pytest.param(
        record_text_with("blocking", "ci", 1000),
        "blocking.ci must be a whole number from 0 to 999",
        id="a-count-past-the-bound",
    ),
    pytest.param(
        record_text_with("blocking", "review", MISSING),
        "blocking lacks 'review'",
        id="a-finding-stage-not-counted",
    ),
    pytest.param(
        json.dumps(lane_record_object(verdicts={})),
        "verdicts must be a list",
        id="verdicts-not-a-list",
    ),
    pytest.param(
        json.dumps(
            lane_record_object(verdicts=[{"stage": "ci", "verdict": "approve", "sha": "a" * 40}])
        ),
        "verdicts[0].stage must be one of review, gate",
        id="a-verdict-of-another-stage",
    ),
    pytest.param(
        json.dumps(
            lane_record_object(verdicts=[{"stage": "gate", "verdict": "ok", "sha": "a" * 40}])
        ),
        "verdicts[0].verdict must be one of approve, revise",
        id="an-unknown-verdict",
    ),
    pytest.param(
        json.dumps(
            lane_record_object(verdicts=[{"stage": "gate", "verdict": "approve", "sha": "abc1234"}])
        ),
        "verdicts[0].sha must be a full 40-digit commit sha",
        id="a-short-sha",
    ),
    pytest.param(
        json.dumps(lane_record_object(risk="very risky")),
        "risk must be 1 to 40 lowercase letters, digits and `-`",
        id="a-risk-with-whitespace",
    ),
    pytest.param(
        json.dumps(lane_record_object(experiment="x" * 41)),
        "experiment must be 1 to 40 lowercase letters, digits and `-`",
        id="an-experiment-past-the-bound",
    ),
]


@pytest.mark.parametrize("text", VALID_RECORDS)
def test_a_valid_record_file_is_accepted_and_left_as_it_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    """Spec: LANREC-30, LANREC-32..LANREC-37."""
    path = tmp_path / "lane-record.json"
    path.write_text(text, encoding="utf-8")

    result = run_cli(["lane-record", "check", str(path)], capsys)

    assert (result.status, result.stdout, result.stderr) == (
        0,
        f"lane record {path} is valid\n",
        "",
    )
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(("text", "defect"), MALFORMED_RECORDS)
def test_a_malformed_record_file_is_refused_with_its_defect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, defect: str
) -> None:
    """Spec: LANREC-31..LANREC-37."""
    path = tmp_path / "lane-record.json"
    path.write_text(text, encoding="utf-8")

    result = run_cli(["lane-record", "check", str(path)], capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        f"ERROR: lane record {path} is invalid: {defect}\n",
    )


def test_a_record_file_that_does_not_exist_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-31."""
    path = tmp_path / "missing.json"

    result = run_cli(["lane-record", "check", str(path)], capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        f"ERROR: lane record {path} is invalid: cannot be read (No such file or directory)\n",
    )


def test_a_record_file_larger_than_the_limit_is_refused_unread(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-31."""
    path = tmp_path / "lane-record.json"
    path.write_bytes(b" " * (lane_record.RECORD_FILE_BYTES_LIMIT + 1))

    result = run_cli(["lane-record", "check", str(path)], capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        f"ERROR: lane record {path} is invalid: cannot be read "
        f"(larger than {lane_record.RECORD_FILE_BYTES_LIMIT} bytes)\n",
    )


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(["lane-record", "check"], id="check"),
        pytest.param(["land", "12", "--head", "a" * 40, "--record"], id="land"),
        pytest.param(["release", "--abandoned", "reason", "--record"], id="release"),
    ],
)
def test_a_refusal_keeps_its_defect_and_the_file_name_however_long_the_file_path_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    """Spec: LANREC-31, LANREC-45."""
    deep = tmp_path.joinpath(*["d" * 25] * 8)
    deep.mkdir(parents=True)
    path = deep / "lane-record.json"
    path.write_text(json.dumps(lane_record_object(version=2)), encoding="utf-8")

    result = run_cli([*command, str(path)], capsys)

    assert result.status == 2
    assert result.stderr.startswith("ERROR: lane record …/")
    assert result.stderr.endswith(
        "/lane-record.json is invalid: version 2 is unknown; this aco reads version 1\n"
    )
    assert len(result.stderr.rstrip("\n")) <= report.REFUSAL_LINE_LENGTH_LIMIT


@pytest.mark.parametrize(
    ("in_working_directory", "shown_prefix"),
    [
        pytest.param(True, "", id="a-bare-file-name"),
        pytest.param(False, "…/", id="a-file-name-in-a-directory"),
    ],
)
def test_a_file_name_longer_than_the_line_stays_whole_and_the_line_passes_the_bound(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    in_working_directory: bool,  # noqa: FBT001
    shown_prefix: str,
) -> None:
    """Spec: LANREC-45."""
    file_name = "a" * 160 + ".json"
    (tmp_path / file_name).write_text(json.dumps(lane_record_object(version=2)), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = run_cli(
        ["lane-record", "check", file_name if in_working_directory else str(tmp_path / file_name)],
        capsys,
    )

    assert result.status == 2
    assert result.stderr == (
        f"ERROR: lane record {shown_prefix}{file_name} is invalid: "
        "version 2 is unknown; this aco reads version 1\n"
    )


def test_a_refusal_cuts_a_long_unknown_key_and_stays_one_bounded_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-31, LANREC-32."""
    path = tmp_path / "lane-record.json"
    path.write_text(json.dumps({**lane_record_object(), "k" * 300: 1}), encoding="utf-8")

    result = run_cli(["lane-record", "check", str(path)], capsys)

    assert result.status == 2
    assert "is invalid: the record has an unknown key 'kkk" in result.stderr
    assert result.stderr.endswith("…\n")
    assert len(result.stderr.rstrip("\n")) <= report.REFUSAL_LINE_LENGTH_LIMIT
