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
    ("text", "fragment"),
    [
        ("code = [", "not valid TOML"),
        ("[[cod]]\n", "unknown top-level key 'cod'"),
        (f"extra = 1\n{listing(VALID_ENTRY)}", "unknown top-level key 'extra'"),
        ("code = 3\n", "'code' must be an array of tables"),
        ("code = [1]\n", "'code' must be an array of tables"),
        (listing('path = "a.py"\nitem = "#1"\n'), "code entry 1 lacks 'reason'"),
        (listing(VALID_ENTRY + 'more = "x"\n'), "code entry 1 has the unknown key 'more'"),
        (listing('path = 3\nitem = "#1"\nreason = "why"\n'), "'path' that is not a string"),
        (listing('path = "/a.py"\nitem = "#1"\nreason = "why"\n'), "path that is not repo"),
        (listing('path = "a\\\\b.py"\nitem = "#1"\nreason = "why"\n'), "path that is not repo"),
        (listing('path = ""\nitem = "#1"\nreason = "why"\n'), "path that is not repo"),
        (listing('path = "a/../b.py"\nitem = "#1"\nreason = "why"\n'), "path that holds a '..'"),
        (listing('path = "a.py"\nitem = "#1"\nreason = ""\n'), "reason that is not one non-empty"),
        (
            listing('path = "a.py"\nitem = "#1"\nreason = "  "\n'),
            "reason that is not one non-empty",
        ),
        (
            listing('path = "a.py"\nitem = "#1"\nreason = "a\\nb"\n'),
            "reason that is not one non-empty",
        ),
        (listing('path = "a.py"\nitem = "x1"\nreason = "why"\n'), "item 'x1'"),
        (listing('path = "a.py"\nitem = "owner/repo"\nreason = "why"\n'), "item 'owner/repo'"),
        (listing('path = "a.py"\nitem = "owner/repo#x"\nreason = "why"\n'), "item 'owner/repo#x'"),
        (listing('path = "a.py"\nitem = "a/b/c#1"\nreason = "why"\n'), "item 'a/b/c#1'"),
        (
            listing(VALID_ENTRY) + listing(VALID_ENTRY.replace('"#12"', '"12"')),
            "code entry 2 repeats the path and item",
        ),
    ],
)
def test_a_malformed_file_is_refused_with_one_sentence_naming_the_field(
    text: str, fragment: str
) -> None:
    """Spec: AHEAD-04, AHEAD-05, AHEAD-06, AHEAD-07, AHEAD-08, AHEAD-09."""
    sentence = unavailable_sentence(text)

    assert fragment in sentence


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
