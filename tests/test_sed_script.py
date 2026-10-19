"""The file names a GNU sed script writes by itself, as pure text reading.
Every row's expectation was measured against GNU sed 4.9: the files it opened
for writing (created or truncated) running the pieces as `-e` values."""

from __future__ import annotations

import pytest

from agent_coordination.sed_script import sed_script_write_targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("w x",), (("x", 0),)),
        (("W x",), (("x", 0),)),
        (("s/a/b/w x",), (("x", 0),)),
        (("w x\nw y",), (("x", 0), ("y", 0))),
        (("w x;p",), (("x;p", 0),)),
        (("w x ",), (("x ", 0),)),
        (("w   x",), (("x", 0),)),
        (("w\tx",), (("x", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_name_the_file_each_write_command_gives_to_the_line_end(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("w",), ()),
        (("w ",), ()),
        (("s/a/b/w",), ()),
        (("s/a/b/w", "x"), ()),
    ],
    ids=repr,
)
def test_sed_script_write_targets_ignore_a_write_without_a_name(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("\rw x",), (("x", 0),)),
        (("p;\x0bw x",), (("x", 0),)),
        (("\x0cw x",), (("x", 0),)),
        (("s/a/b/\r\nw x",), (("x", 0),)),
        (("{\rw x\n}",), (("x", 0),)),
        (("{\x0bw x\n}",), (("x", 0),)),
        (("{\x0cw x\n}",), (("x", 0),)),
        (("w x\r",), (("x\r", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_skip_the_blanks_between_commands_and_after_a_block_start(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("p\rw x",), ()),
        (("1\rw x",), ()),
        (("{p}\rw x",), ()),
        (("s/a/b/\rw x",), ()),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_a_carriage_return_inside_a_command_as_a_gnu_error(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("1w x",), (("x", 0),)),
        (("$w x",), (("x", 0),)),
        (("1~2w x",), (("x", 0),)),
        (("0~4w x",), (("x", 0),)),
        (("/a/w x",), (("x", 0),)),
        (("/a/Iw x",), (("x", 0),)),
        (("/a/IMw x",), (("x", 0),)),
        (("\\,a,w x",), (("x", 0),)),
        (("1,3w x",), (("x", 0),)),
        (("1,+2w x",), (("x", 0),)),
        (("1,~2w x",), (("x", 0),)),
        (("/a/,/b/w x",), (("x", 0),)),
        (("1 , 3 w x",), (("x", 0),)),
        (("1!w x",), (("x", 0),)),
        (("1 ! w x",), (("x", 0),)),
        (("!w x",), (("x", 0),)),
        (("1,$!w x",), (("x", 0),)),
        (("\\\\a\\w x",), (("x", 0),)),
        (("s\\a\\b\\w x",), (("x", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_every_address_form(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("/[/]/w x",), (("x", 0),)),
        (("s/[/]/x/w x",), (("x", 0),)),
        (("/[]/]/w x",), (("x", 0),)),
        (("/[^]/]/w x",), (("x", 0),)),
        (("/[[:alpha:]/]/w x",), (("x", 0),)),
        (("s/a/[/w x",), (("x", 0),)),
        (("y/[/]/\nw x",), (("x", 0),)),
        (("/a\\/b/w x",), (("x", 0),)),
        (("s/a\\/b/c/w x",), (("x", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_regex_brackets_and_escapes_as_part_of_the_pattern(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("a w x",), ()),
        (("a\\\nw x",), ()),
        (("a foo\nw x",), (("x", 0),)),
        (("a\nw x",), (("x", 0),)),
        (("a\\ \nw x",), (("x", 0),)),
        (("a\\\\\nw x",), (("x", 0),)),
        (("a\\ \\\nw x",), ()),
        (("a\\\\\\\nw x",), ()),
        (("a foo\\\nw x",), ()),
        (("i\\ \nw x",), (("x", 0),)),
        (("c\\\\\nw x",), (("x", 0),)),
        (("e\\ \nw x",), (("x", 0),)),
        (("e\nw x",), (("x", 0),)),
        (("a",), ()),
        (("a\\", "w x"), ()),
        (("e\\", "w x"), ()),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_text_commands_as_text_to_the_unescaped_line_end(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("b a\rw x",), ()),
        (("b a w x",), (("x", 0),)),
        (("ba;w x",), (("x", 0),)),
        (("{b a}\nw x",), (("x", 0),)),
        ((":a;w x",), (("x", 0),)),
        (("t;w x",), (("x", 0),)),
        (("T a;w x",), (("x", 0),)),
        (("v;w x",), (("x", 0),)),
        (("l 5;w x",), (("x", 0),)),
        (("q5\nw x",), (("x", 0),)),
        (("Q;w x",), (("x", 0),)),
        (("l\rw x",), ()),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_labels_and_numbers_before_the_next_command(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("s/a/b/gpw x",), (("x", 0),)),
        (("s/a/b/ w x",), (("x", 0),)),
        (("s/a/b/ggw x",), ()),
        (("s/a/b/2 3w x",), ()),
        (("s/a/b/0w x",), ()),
        (("s/a/b/ppw x",), ()),
        (("s/a/b/2gw x",), (("x", 0),)),
        (("s/a/b/Iw x",), (("x", 0),)),
        (("s/a/b/xw y",), ()),
        (("s/a/b/;w x",), (("x", 0),)),
        (("s/a/b/#c\nw x",), (("x", 0),)),
        (("s/a/b/\nw x",), (("x", 0),)),
        (("s,a,b,w x",), (("x", 0),)),
        (("s/a/b",), ()),
        (("s/a\nb/c/w x",), ()),
        (("s/a/b\nc/w x",), ()),
        (("s/a/b/²w x",), ()),
    ],
    ids=repr,
)
def test_sed_script_write_targets_read_the_substitute_flags_up_to_a_write(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("#w x",), ()),
        (("p # w x\nw y",), (("y", 0),)),
        (("y/w/x/",), ()),
        (("s/a/w x/",), ()),
        (("/w x/p",), ()),
        (("r w x",), ()),
        (("R w x",), ()),
        (("r w x\nw y",), (("y", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_name_nothing_for_commands_that_write_no_file(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("w y\nk\nw x",), (("y", 0),)),
        (("w y\np p\nw x",), (("y", 0),)),
        (("w y\ns/a/b/ggw z",), (("y", 0),)),
        (("e",), ()),
        (("w y\ne",), (("y", 0),)),
        (("s",), ()),
        (("y\nw x",), ()),
        (("w y\n/[a",), (("y", 0),)),
        (("w y\n/[a\n]/w x",), (("y", 0),)),
        (("w y\n/[[:alpha",), (("y", 0),)),
        (("w y\n1,w x",), (("y", 0),)),
    ],
    ids=repr,
)
def test_sed_script_write_targets_stop_at_the_first_construct_gnu_sed_rejects(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets


@pytest.mark.parametrize(
    ("pieces", "targets"),
    [
        (("p", "\rw x"), (("x", 1),)),
        (("w x", "w y"), (("x", 0), ("y", 1))),
        (("", "w x"), (("x", 1),)),
        ((), ()),
        (("p\nw x", "w y"), (("x", 0), ("y", 1))),
    ],
    ids=repr,
)
def test_sed_script_write_targets_join_the_pieces_with_a_line_end_and_name_the_piece_of_each_file(
    pieces: tuple[str, ...], targets: tuple[tuple[str, int], ...]
) -> None:
    assert sed_script_write_targets(pieces) == targets
