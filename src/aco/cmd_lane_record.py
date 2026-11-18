"""The `lane-record` command (`specs/lane-record.spec.md`)."""
# ruff: noqa: T201 - the lane-record command writes its result line to stdout

import argparse
from pathlib import Path

from . import lane_record, protocol, report, usage
from .session import RunContext

_INVALID = "lane record {foreign} is invalid: {defect}"
# A value the file states is cut to this, so the refusal keeps its own words and the file's path
# keeps room on one bounded line.
_STATED_VALUE_LENGTH_LIMIT = 40


def read_record_file(path_text: str) -> lane_record.LaneRecordFile:
    """The lane record file at `path_text`, read once and validated whole; one that is not
    exactly what the spec states refuses, naming the first thing wrong with it."""
    try:
        return lane_record.parse_record_file(Path(path_text).read_bytes())
    except OSError as error:
        defect = f"cannot be read ({error.strerror})"
    except lane_record.RecordFileError as error:
        stated = report.cut_foreign_text(error.stated, _STATED_VALUE_LENGTH_LIMIT)
        defect = error.before + stated + error.after
    raise protocol.ClaimUnavailableError(
        report.refusal_around_foreign_text(_INVALID, path_text, defect=defect)
    )


def add_record_argument(command: argparse.ArgumentParser, *, writes: str) -> None:
    """`--record FILE` of a command that `writes` a release: the file is read and validated by
    the argument parse, so a malformed one refuses before the command reads or writes anything."""
    command.add_argument(
        "--record",
        metavar="FILE",
        type=read_record_file,
        help=f"the lane record file whose figures {writes}; a malformed file refuses",
    )


def add_parser(commands: usage.Subcommands, name: str) -> None:
    command = commands.add_parser(name, help="check a lane record file, read-only")
    command.subcommands = usage.Subcommands(command, "lane_record_command")
    check = command.subcommands.add_parser(
        "check", help="say whether FILE is a valid lane record file, and why not"
    )
    check.add_argument("file", metavar="FILE", help="the lane record file to check")


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    read_record_file(parsed.file)
    print(f"lane record {protocol.terminal_text(parsed.file)} is valid")
    return 0
