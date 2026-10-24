"""The argument parser every `aco` command line is read with: it raises a
refusal instead of exiting inside the parse, so one place decides its shape."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from typing import NoReturn, TypedDict, TypeVar, Unpack, cast, overload

from . import protocol


class UsageError(protocol.ClaimError):
    """One refusal the argument parser itself raises -- an unknown flag, a
    missing required option, a mutually exclusive pair -- carried out of the
    parse instead of exiting inside it (issue #432), so a `--json` caller
    still gets the shared envelope. `parser` is the one that refused, a
    subcommand's own rather than the root's, because only it can print the
    usage block the plain-text path still prints byte for byte."""

    def __init__(self, parser: argparse.ArgumentParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser


_Namespace = TypeVar("_Namespace")


class _ArgumentOptions(TypedDict, total=False):
    """The `add_argument` options `aco` parsers declare, as typeshed types them."""

    action: str | type[argparse.Action]
    nargs: int | str | None
    const: object
    default: object
    type: Callable[[str], object] | argparse.FileType | str
    choices: Iterable[object] | None
    required: bool
    help: str | None
    metavar: str | tuple[str, ...] | None
    dest: str | None
    version: str


class UsageErrorParser(argparse.ArgumentParser):
    """Every `aco` parser and subparser -- argparse hands this class down to
    each subparser it builds. Its own refusal path prints usage and exits
    inside the parse, before `--json` was ever read off a namespace, so this
    raises instead and lets one place decide the refusal's shape.

    No parser reads an abbreviated long option (issue #502, OUT-09): a
    prefix unique today targets another option once one is added, and
    `reset --conf --f` must never stand for a destructive flag pair.

    It also remembers what a refused parse would otherwise lose (issue #432):
    Python parses a subcommand into a throwaway namespace and copies the
    values back only once that parse succeeds, yet `--json` is exactly the
    flag the refusal's own shape depends on. So each parser keeps the tokens
    it was handed and the arguments declared on it, and `subcommands` names
    the parsers one level down."""

    def __init__(self, *, prog: str | None = None, description: str | None = None) -> None:
        self.declared_actions: list[argparse.Action] = []
        self.received_tokens: tuple[str, ...] | None = None
        self.subcommands: Subcommands | None = None
        super().__init__(prog=prog, description=description, allow_abbrev=False)

    def add_argument(
        self, *name_or_flags: str, **options: Unpack[_ArgumentOptions]
    ) -> argparse.Action:
        action = super().add_argument(*name_or_flags, **options)
        self.declared_actions.append(action)
        return action

    @overload
    def parse_known_args(
        self, args: Iterable[str] | None = None, namespace: None = None
    ) -> tuple[argparse.Namespace, list[str]]: ...

    @overload
    def parse_known_args(
        self, args: Iterable[str] | None, namespace: _Namespace
    ) -> tuple[_Namespace, list[str]]: ...

    @overload
    def parse_known_args(self, *, namespace: _Namespace) -> tuple[_Namespace, list[str]]: ...

    def parse_known_args(
        self, args: Iterable[str] | None = None, namespace: _Namespace | None = None
    ) -> tuple[_Namespace | argparse.Namespace, list[str]]:
        if self.subcommands:
            self.subcommands.forget_received_tokens()
        self.received_tokens = tuple(sys.argv[1:] if args is None else args)
        parsed = super().parse_known_args(self.received_tokens, namespace)
        return cast("tuple[_Namespace | argparse.Namespace, list[str]]", parsed)

    def error(self, message: str) -> NoReturn:
        raise UsageError(self, message)


class Subcommands:
    """The subcommand level of one `aco` parser: builders add their command
    through it, and a refused parse can ask which command was chosen (the
    one that was handed tokens)."""

    def __init__(self, parent: UsageErrorParser, dest: str) -> None:
        self._action = parent.add_subparsers(dest=dest, required=True)

    def add_parser(
        self, name: str, *, help: str, description: str | None = None
    ) -> UsageErrorParser:
        return self._action.add_parser(name, help=help, description=description)

    def chosen(self) -> tuple[UsageErrorParser, tuple[str, ...]] | None:
        return next(
            (
                (parser, parser.received_tokens)
                for parser in self._action.choices.values()
                if parser.received_tokens is not None
            ),
            None,
        )

    def forget_received_tokens(self) -> None:
        """A reused parser must not report the command an earlier parse chose."""
        for parser in self._action.choices.values():
            parser.received_tokens = None
            if parser.subcommands:
                parser.subcommands.forget_received_tokens()
