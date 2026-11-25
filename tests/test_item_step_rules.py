"""The rules the `step` tool applies to a new step (`specs/mcp.spec.md`, MCP-90 to MCP-93):
word limits, one line, and one link or one command as the paste."""

import pytest

from aco import item_step

_ONE_LINE = "paste must be one line; write a script and paste its one call"
_LINK = "paste is a link and must start with https:// or http://127.0.0.1, without spaces"


def _chained(token: str) -> str:
    return f'paste must be one command, it holds "{token}"; write a script and paste its one call'


def _defects(
    *,
    step: str = "Rotate the key.",
    purpose: str = "The old key leaked.",
    paste: str = "make rotate",
    expected: str = "A new key shows.",
) -> list[str]:
    return item_step.step_rule_defects(step, purpose, paste, expected)


def _words(count: int) -> str:
    return " ".join(["word"] * count)


@pytest.mark.parametrize(
    ("fields", "defects"),
    [
        pytest.param({}, [], id="valid"),
        pytest.param({"step": _words(15)}, [], id="step-fifteen-words"),
        pytest.param(
            {"step": _words(16)}, ["step must be at most 15 words"], id="step-sixteen-words"
        ),
        pytest.param({"purpose": _words(20)}, [], id="purpose-twenty-words"),
        pytest.param(
            {"purpose": _words(21)},
            ["purpose must be at most 20 words"],
            id="purpose-twenty-one-words",
        ),
        pytest.param({"expected": _words(20)}, [], id="expected-twenty-words"),
        pytest.param(
            {"expected": _words(21)},
            ["expected must be at most 20 words"],
            id="expected-twenty-one-words",
        ),
        pytest.param({"step": "Do a\nthen b."}, ["step must be one line"], id="step-two-lines"),
        pytest.param(
            {"purpose": "Why a\nand b."}, ["purpose must be one line"], id="purpose-two-lines"
        ),
        pytest.param(
            {"expected": "See a\r\nand b."}, ["expected must be one line"], id="expected-crlf"
        ),
        pytest.param(
            {"step": _words(16) + "\nmore"},
            ["step must be at most 15 words", "step must be one line"],
            id="step-both-defects",
        ),
        pytest.param(
            {"step": _words(16), "paste": "a\nb"},
            ["step must be at most 15 words", _ONE_LINE],
            id="defects-in-field-order",
        ),
    ],
)
def test_a_step_line_purpose_and_expected_keep_to_their_words_and_one_line(
    fields: dict[str, str], defects: list[str]
) -> None:
    """Spec: MCP-90"""
    assert _defects(**fields) == defects


@pytest.mark.parametrize(
    "paste",
    [
        pytest.param("a\nb", id="two-lines"),
        pytest.param("a\n", id="trailing-newline"),
        pytest.param("a\rb", id="carriage-return"),
        pytest.param("https://example.test/a\nhttps://example.test/b", id="two-links"),
    ],
)
def test_a_paste_over_one_line_is_refused(paste: str) -> None:
    """Spec: MCP-91. Example: E-MCP-22."""
    assert _defects(paste=paste) == [_ONE_LINE]


@pytest.mark.parametrize(
    ("paste", "defects"),
    [
        pytest.param("https://example.test/run", [], id="https"),
        pytest.param("http://127.0.0.1", [], id="loopback"),
        pytest.param("http://127.0.0.1:8765/#t=abc&s=owner/a/9", [], id="loopback-with-port"),
        pytest.param("http://127.0.0.1/board", [], id="loopback-with-path"),
        pytest.param("http://127.0.0.1.example.test/x", [_LINK], id="loopback-lookalike"),
        pytest.param("http://127.0.0.10/x", [_LINK], id="other-loopback-address"),
        pytest.param("http://127.0.0.1:80@evil.example/x", [_LINK], id="loopback-userinfo-host"),
        pytest.param("http://127.0.0.1:@evil.example/x", [_LINK], id="loopback-empty-port-host"),
        pytest.param("http://example.test/x", [_LINK], id="http-elsewhere"),
        pytest.param("ftp://host/x", [_LINK], id="ftp"),
        pytest.param("file:///etc/passwd", [_LINK], id="file"),
        pytest.param("HTTPS://example.test/x", [_LINK], id="uppercase-scheme"),
        pytest.param("https://example.test/a b", [_LINK], id="space-in-link"),
        pytest.param("https://", [_LINK], id="scheme-only"),
    ],
)
def test_a_link_paste_is_https_or_loopback_http_without_spaces(
    paste: str, defects: list[str]
) -> None:
    """Spec: MCP-92. Example: E-MCP-22."""
    assert _defects(paste=paste) == defects


@pytest.mark.parametrize(
    ("paste", "defects"),
    [
        pytest.param("make rotate", [], id="plain"),
        pytest.param("xdg-open /tmp/report.html", [], id="open-a-file"),
        pytest.param("cd ~/git/aco && make rotate", [], id="cd-then-command"),
        pytest.param('KEY="a b" make rotate', [], id="quoted-argument"),
        pytest.param("javascript:alert(1)", [], id="no-slashes-is-no-link"),
        pytest.param("cd a && make b && make c", [_chained("&&")], id="second-and"),
        pytest.param("cd a; make b", [_chained(";")], id="cd-then-semicolon"),
        pytest.param("make a; make b", [_chained(";")], id="semicolon"),
        pytest.param("make a || make b", [_chained("||")], id="or"),
        pytest.param("make a | tee log", [_chained("|")], id="pipe"),
        pytest.param("make a &", [_chained("&")], id="background"),
        pytest.param("make $(date)", [_chained("$(")], id="substitution"),
        pytest.param("make `date`", [_chained("`")], id="backtick"),
        pytest.param("make a && make b", [_chained("&&")], id="chain-without-cd"),
        pytest.param("cd a;b && make c", [_chained("&&")], id="cd-word-with-semicolon"),
    ],
)
def test_a_command_paste_holds_one_command_after_an_optional_cd(
    paste: str, defects: list[str]
) -> None:
    """Spec: MCP-93. Example: E-MCP-22."""
    assert _defects(paste=paste) == defects


@pytest.mark.parametrize(
    ("paste", "kind"),
    [
        pytest.param("https://example.test/run", item_step.PasteKind.LINK, id="https"),
        pytest.param("ftp://host/x", item_step.PasteKind.LINK, id="any-scheme"),
        pytest.param("make rotate", item_step.PasteKind.COMMAND, id="command"),
        pytest.param("javascript:alert(1)", item_step.PasteKind.COMMAND, id="no-slashes"),
        pytest.param("make https://example.test", item_step.PasteKind.COMMAND, id="url-in-command"),
    ],
)
def test_a_paste_starting_with_a_scheme_and_slashes_is_a_link(
    paste: str, kind: item_step.PasteKind
) -> None:
    """Spec: MCP-92, MCP-93"""
    assert item_step.paste_kind(paste) is kind
