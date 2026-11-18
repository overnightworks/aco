"""The `lane-record` command (`specs/lane-record.spec.md`)."""
# ruff: noqa: T201 - the lane-record command writes its result line to stdout

import argparse

from . import lane_record, protocol, usage
from .session import RunContext


def add_record_argument(command: argparse.ArgumentParser, *, writes: str) -> None:
    """`--record FILE` of a command that `writes` a release: the file is read and validated by
    the argument parse, so a malformed one refuses before the command reads or writes anything."""
    command.add_argument(
        "--record",
        metavar="FILE",
        type=lane_record.read_record_file,
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
    lane_record.read_record_file(parsed.file)
    print(f"lane record {protocol.terminal_text(parsed.file)} is valid")
    return 0
