"""The pure parser and red verdict of the list of code built ahead of its
caller (`specs/ahead-of-caller.spec.md`)."""

import pytest

from aco import ahead_of_caller, forge, github

VALID_ENTRY = 'path = "src/token.py"\nitem = "#12"\nreason = "token helper"\n'


def listing(entry: str) -> str:
    return f"[[code]]\n{entry}"


def unavailable_sentence(text: str) -> str:
    parsed = ahead_of_caller.parse(text)
    assert isinstance(parsed, ahead_of_caller.Unavailable)
    return parsed.sentence


@pytest.mark.parametrize("text", ["", "\n# only a comment\n", "code = []\n"])
def test_a_file_without_entries_holds_none(text: str) -> None:
    """Spec: AHEAD-01."""
    assert ahead_of_caller.parse(text) == ()


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ("#12", ahead_of_caller.ItemTarget(None, 12)),
        ("12", ahead_of_caller.ItemTarget(None, 12)),
        ("aco-00000c", ahead_of_caller.ItemTarget(None, 12)),
        ("owner/repo#7", ahead_of_caller.ItemTarget(github.repository_id("owner/repo"), 7)),
    ],
)
def test_an_item_takes_the_forms_of_this_repository_or_another(
    item: str, expected: ahead_of_caller.ItemTarget
) -> None:
    """Spec: AHEAD-08."""
    text = listing(f'path = "a.py"\nitem = "{item}"\nreason = "why"\n')

    assert ahead_of_caller.parse(text) == (ahead_of_caller.Entry("a.py", expected, "why"),)


@pytest.mark.parametrize(
    ("text", "sentence"),
    [
        ("[[cod]]\n", ".aco/ahead-of-caller.toml has the unknown top-level key 'cod'"),
        (
            f"extra = 1\n{listing(VALID_ENTRY)}",
            ".aco/ahead-of-caller.toml has the unknown top-level key 'extra'",
        ),
        ("code = 3\n", ".aco/ahead-of-caller.toml: 'code' must be an array of tables"),
        ("code = [1]\n", ".aco/ahead-of-caller.toml: 'code' must be an array of tables"),
        (
            listing('path = "a.py"\nitem = "#1"\n'),
            ".aco/ahead-of-caller.toml: code entry 1 lacks 'reason'",
        ),
        (
            listing(VALID_ENTRY + 'more = "x"\n'),
            ".aco/ahead-of-caller.toml: code entry 1 has the unknown key 'more'",
        ),
        (
            listing('path = 3\nitem = "#1"\nreason = "why"\n'),
            ".aco/ahead-of-caller.toml: code entry 1 has 'path' that is not a string",
        ),
        *[
            (
                listing(f'path = "{path}"\nitem = "#1"\nreason = "why"\n'),
                ".aco/ahead-of-caller.toml: code entry 1 has a path that is not "
                "repository-relative with forward slashes",
            )
            for path in ("/a.py", "a\\\\b.py", "")
        ],
        (
            listing('path = "a/../b.py"\nitem = "#1"\nreason = "why"\n'),
            ".aco/ahead-of-caller.toml: code entry 1 has a path that holds a '..' segment",
        ),
        *[
            (
                listing(f'path = "a.py"\nitem = "#1"\nreason = "{reason}"\n'),
                ".aco/ahead-of-caller.toml: code entry 1 has a reason that is not one "
                "non-empty line",
            )
            for reason in ("", "  ", "a\\nb")
        ],
        *[
            (
                listing(f'path = "a.py"\nitem = "{item}"\nreason = "why"\n'),
                f".aco/ahead-of-caller.toml: code entry 1 has an item '{item}' that is not "
                "aco-xxxxxx, #n, n or OWNER/REPO#n",
            )
            for item in ("x1", "owner/repo", "owner/repo#x", "a/b/c#1")
        ],
        (
            listing(VALID_ENTRY) + listing(VALID_ENTRY.replace('"#12"', '"12"')),
            ".aco/ahead-of-caller.toml: code entry 2 repeats the path and item of an earlier entry",
        ),
        (
            listing('path = "a.py"\nitem = "x1"\nreason = ""\n'),
            ".aco/ahead-of-caller.toml: code entry 1 has a reason that is not one non-empty line",
        ),
    ],
)
def test_a_malformed_file_is_refused_with_its_spec_sentence(text: str, sentence: str) -> None:
    """Spec: AHEAD-04..AHEAD-09, AHEAD-16..AHEAD-19."""
    assert unavailable_sentence(text) == sentence


def test_bad_toml_is_refused_with_the_parsers_text_after_the_spec_sentence() -> None:
    """Spec: AHEAD-04."""
    sentence = unavailable_sentence("code = [")

    assert sentence.startswith(".aco/ahead-of-caller.toml is not valid TOML: ")
    assert len(sentence) > len(".aco/ahead-of-caller.toml is not valid TOML: ")


def test_the_same_path_may_wait_on_two_items() -> None:
    """Spec: AHEAD-09."""
    text = listing(VALID_ENTRY) + listing(VALID_ENTRY.replace('"#12"', '"#13"'))

    parsed = ahead_of_caller.parse(text)

    assert isinstance(parsed, tuple)
    assert [entry.item.number for entry in parsed] == [12, 13]


@pytest.mark.parametrize(
    ("reference", "state", "red"),
    [
        (forge.ItemReference(forge.ItemState.OPEN), ahead_of_caller.ItemState.OPEN, False),
        (forge.ItemReference(forge.ItemState.CLOSED), ahead_of_caller.ItemState.CLOSED, True),
        (forge.ItemReference(forge.ItemState.MISSING), ahead_of_caller.ItemState.MISSING, True),
        (
            forge.ItemReference(forge.ItemState.OPEN, is_landing=True),
            ahead_of_caller.ItemState.PULL_REQUEST,
            True,
        ),
        (
            forge.ItemReference(forge.ItemState.CLOSED, is_landing=True),
            ahead_of_caller.ItemState.PULL_REQUEST,
            True,
        ),
    ],
)
def test_only_an_open_item_is_silent(
    reference: forge.ItemReference, state: ahead_of_caller.ItemState, red: bool
) -> None:
    """Spec: AHEAD-12."""
    assert ahead_of_caller.state_of(reference) is state
    assert ahead_of_caller.is_red(state) is red


def test_an_unreadable_item_is_red() -> None:
    """Spec: AHEAD-12."""
    assert ahead_of_caller.is_red(ahead_of_caller.ItemState.UNREADABLE)
