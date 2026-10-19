"""The files a GNU `sed` script writes by itself: `w FILE`, `W FILE` and the
`w` flag of `s///`. GNU sed opens (and truncates) each of them while it
compiles the script, before any later option is read and whatever a later
error does, so the hook judges them like any other write pattern.

Pure text reading of the script grammar as GNU sed 4.9 measures it, no
filesystem or process. The reader stops at the first construct it knows GNU
sed rejects (an unknown command, a missing argument, a repeated `s` flag, ...):
everything before it was already opened, text behind it is never compiled.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from typing import NamedTuple

_BLANKS = frozenset(" \t")
_BETWEEN_COMMANDS = frozenset(" \t\r\v\f\n;")
_DIGITS = frozenset("0123456789")
_LINE_END = frozenset("\n")
_COMMAND_END = frozenset({"", "\n", ";"})
_COMMANDS_ENDING_THERE = frozenset("}=dDgGhHnNpPxzF")
_COMMANDS_WITH_LABEL = frozenset(":btTv")
_COMMANDS_WITH_NUMBER = frozenset("lLqQ")
_TEXT_COMMANDS = frozenset("aice")
_FILE_READING_COMMANDS = frozenset("rR")
_FILE_WRITING_COMMANDS = frozenset("wW")
_LABEL_END = frozenset(" \t\n;}#")
_BRACKET_CLASS_OPENERS = frozenset(":.=")
_ADDRESS_FLAGS = frozenset("IM")
_RELATIVE_ADDRESS_MARKS = frozenset("+~")
_SUBSTITUTE_PLAIN_FLAGS = frozenset("iImMe \t")
_SUBSTITUTE_ONCE_FLAGS = frozenset("gp")
_BLOCK_OR_COMMENT_START = frozenset("}#")
_NUMBERED_FLAG = "number"
_CARRIAGE_RETURN_LINE_FEED = "\r\n"


class SedWriteTarget(NamedTuple):
    name: str
    piece: int  # index of the script piece (an `-e` value or the positional one) it starts in


class _Name(NamedTuple):
    text: str
    start: int


class _RejectedScriptError(Exception):
    """GNU sed refuses the script from here on; the rest is never compiled."""


class _ScriptReader:
    def __init__(self, script: str) -> None:
        self._script = script
        self._at = 0

    def skip_to_next_command(self) -> bool:
        while self._peek() in _BETWEEN_COMMANDS:
            self._take()
        return bool(self._peek())

    def read_command(self) -> _Name | None:
        """One command with its addresses; its written file name, if it has one."""
        self._addresses()
        self._skip_blanks()
        char = self._take()
        if char in _FILE_WRITING_COMMANDS or char in _FILE_READING_COMMANDS:
            name = self._file_name()
            return name if char in _FILE_WRITING_COMMANDS else None
        if char == "s":
            return self._substitute()
        self._command_without_file(char)
        return None

    def _peek(self) -> str:
        return self._script[self._at] if self._at < len(self._script) else ""

    def _take(self) -> str:
        char = self._peek()
        self._at += len(char)
        return char

    def _skip_blanks(self) -> None:
        while self._peek() in _BLANKS:
            self._take()

    def _skip_digits(self) -> str:
        start = self._at
        while self._peek() in _DIGITS:
            self._take()
        return self._script[start : self._at]

    def _rest_of_line(self) -> str:
        end = self._script.find("\n", self._at)
        line = self._script[self._at : end if end >= 0 else len(self._script)]
        self._at += len(line)
        return line

    def _file_name(self) -> _Name:
        self._skip_blanks()
        start = self._at
        name = self._rest_of_line()
        if not name:
            raise _RejectedScriptError
        return _Name(name, start)

    def _command_without_file(self, char: str) -> None:
        if char == "#":
            self._rest_of_line()
        elif char == "{":
            return
        elif char in _COMMANDS_ENDING_THERE:
            self._end_of_command()
        elif char in _TEXT_COMMANDS:
            self._text_command(char)
        elif char in _COMMANDS_WITH_LABEL:
            self._label()
        elif char in _COMMANDS_WITH_NUMBER:
            self._skip_blanks()
            self._skip_digits()
            self._end_of_command()
        elif char == "y":
            self._transliterate()
        else:
            raise _RejectedScriptError

    def _end_of_command(self) -> None:
        self._skip_blanks()
        if self._peek() in _COMMAND_END:
            self._take()
        elif self._peek() not in _BLOCK_OR_COMMENT_START:
            raise _RejectedScriptError

    def _label(self) -> None:
        self._skip_blanks()
        while self._peek() and self._peek() not in _LABEL_END:
            self._take()

    def _text_command(self, command: str) -> None:
        self._skip_blanks()
        if not self._peek():
            if command != "e":
                raise _RejectedScriptError
            return
        if self._peek() == "\\":
            self._take()
            # the line end of `a\` or, whatever it is, the first text character: literal
            self._take()
        self._text_to_unescaped_line_end()

    def _text_to_unescaped_line_end(self) -> None:
        while (char := self._take()) and char not in _LINE_END:
            if char == "\\":
                self._take()

    def _transliterate(self) -> None:
        delimiter = self._delimiter()
        self._skip_delimited(delimiter, with_brackets=False)
        self._skip_delimited(delimiter, with_brackets=False)
        self._end_of_command()

    def _delimiter(self) -> str:
        delimiter = self._take()
        if not delimiter or delimiter in _LINE_END:
            raise _RejectedScriptError
        return delimiter

    def _skip_delimited(self, delimiter: str, *, with_brackets: bool) -> None:
        while (char := self._take()) != delimiter:
            if not char or char in _LINE_END:
                raise _RejectedScriptError
            if char == "\\":
                self._take()
            elif char == "[" and with_brackets:
                self._skip_bracket_expression()

    def _skip_bracket_expression(self) -> None:
        if self._peek() == "^":
            self._take()
        if self._peek() == "]":
            self._take()
        while (char := self._take()) != "]":
            if not char or char in _LINE_END:
                raise _RejectedScriptError
            if char == "[" and self._peek() in _BRACKET_CLASS_OPENERS:
                self._skip_bracket_class(self._take())

    def _skip_bracket_class(self, opener: str) -> None:
        closer = opener + "]"
        while not self._script.startswith(closer, self._at):
            if not self._take():
                raise _RejectedScriptError
        self._at += len(closer)

    def _addresses(self) -> None:
        if self._address():
            self._skip_blanks()
            if self._peek() == ",":
                self._take()
                self._skip_blanks()
                if not self._address():
                    raise _RejectedScriptError
            self._skip_blanks()
        if self._peek() == "!":
            self._take()
            self._skip_blanks()

    def _address(self) -> bool:
        char = self._peek()
        if char in _DIGITS:
            self._line_or_step_address()
        elif char == "$":
            self._take()
        elif char in _RELATIVE_ADDRESS_MARKS:
            self._relative_address()
        elif char in {"/", "\\"}:
            self._regex_address()
        else:
            return False
        return True

    def _line_or_step_address(self) -> None:
        self._skip_digits()
        self._skip_blanks()
        if self._peek() == "~":
            self._take()
            self._skip_blanks()
            self._skip_digits()

    def _relative_address(self) -> None:
        self._take()
        self._skip_blanks()
        self._skip_digits()

    def _regex_address(self) -> None:
        delimiter = "/" if self._take() == "/" else self._delimiter()
        self._skip_delimited(delimiter, with_brackets=True)
        self._skip_blanks()
        while self._peek() in _ADDRESS_FLAGS:
            self._take()
            self._skip_blanks()

    def _substitute(self) -> _Name | None:
        delimiter = self._delimiter()
        self._skip_delimited(delimiter, with_brackets=True)
        self._skip_delimited(delimiter, with_brackets=False)
        given_once: set[str] = set()
        while not self._substitute_ended():
            if self._peek() == "w":
                self._take()
                return self._file_name()
            self._substitute_flag(given_once)
        return None

    def _substitute_ended(self) -> bool:
        char = self._peek()
        if char in _COMMAND_END:
            self._take()
        elif char == "\r" and self._script.startswith(_CARRIAGE_RETURN_LINE_FEED, self._at):
            # the one place in a command where GNU sed reads a CR LF line end
            self._at += len(_CARRIAGE_RETURN_LINE_FEED)
        elif char not in _BLOCK_OR_COMMENT_START:
            return False
        return True

    def _substitute_flag(self, given_once: set[str]) -> None:
        char = self._peek()
        if char in _DIGITS:
            self._reject_repeat(given_once, _NUMBERED_FLAG)
            if not self._skip_digits().lstrip("0"):
                raise _RejectedScriptError
        elif char in _SUBSTITUTE_ONCE_FLAGS:
            self._reject_repeat(given_once, self._take())
        elif char in _SUBSTITUTE_PLAIN_FLAGS:
            self._take()
        else:
            raise _RejectedScriptError

    @staticmethod
    def _reject_repeat(given_once: set[str], flag: str) -> None:
        if flag in given_once:
            raise _RejectedScriptError
        given_once.add(flag)


def sed_script_write_targets(pieces: Sequence[str]) -> tuple[SedWriteTarget, ...]:
    """The file names the script `pieces` write, in script order; each piece
    is one `-e` value or the positional script, which GNU sed joins with a
    line end."""
    piece_starts = [0]
    for piece in pieces:
        piece_starts.append(piece_starts[-1] + len(piece) + 1)
    reader = _ScriptReader("\n".join(pieces))
    targets: list[SedWriteTarget] = []
    try:
        while reader.skip_to_next_command():
            name = reader.read_command()
            if name is not None:
                piece = bisect_right(piece_starts, name.start) - 1
                targets.append(SedWriteTarget(name.text, piece))
    except _RejectedScriptError:
        pass
    return tuple(targets)
