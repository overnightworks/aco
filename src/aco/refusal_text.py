"""The length bound of one refusal line and the cuts of foreign text inside it."""

from . import protocol

CLI_ERROR_PREFIX = "ERROR: "
REFUSAL_LINE_LENGTH_LIMIT = 200
REFUSAL_SENTENCE_LENGTH_LIMIT = REFUSAL_LINE_LENGTH_LIMIT - len(CLI_ERROR_PREFIX)


def cut_foreign_text(foreign_text: str, limit: int) -> str:
    """`foreign_text` shown as `bounded_refusal` shows foreign text, cut to `limit` characters."""
    printable = protocol.terminal_text(foreign_text)
    if len(printable) <= limit:
        return printable
    return printable[: limit - 1] + "…"


def foreign_text_room(fixed_words: str, *, reserved: int = 0) -> int:
    """The characters foreign text may take in a refusal sentence whose other words are
    `fixed_words`, after `reserved` characters a caller prints before the sentence."""
    return REFUSAL_SENTENCE_LENGTH_LIMIT - reserved - len(fixed_words)
