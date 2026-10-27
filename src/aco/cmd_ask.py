"""The `ask` command (`specs/ask.spec.md`)."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from . import body, cmd_rule, expectation_grammar, expectations, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`ask`'s own flags; the `--json` flag stays `cli`'s one declaration."""
    parser.add_argument(
        "item",
        type=workboard.parse_item_reference,
        help="the item to append the expectation line to",
    )
    parser.add_argument("--text", required=True, help="the expectation line's prose")
    parser.add_argument(
        "--default",
        choices=sorted(expectation_grammar.BLOCK_EXPECTATION_DEFAULTS),
        default="yes",
        help="the proposer's suggested outcome; default yes",
    )
    parser.add_argument(
        "--question",
        help=(
            "one operator-language sentence the card shows as its heading instead of --text; "
            f"at most {expectation_grammar.EXPECTATION_QUESTION_MAXIMUM_CHARACTERS} characters"
        ),
    )
    parser.add_argument(
        "--example", help="one operator-language sentence illustrating the question"
    )
    parser.add_argument(
        "--picture",
        metavar="FILE.svg",
        help=(
            "a path to an inline-SVG file (root <svg>, no <script>, no external "
            f"href, at most {expectation_grammar.EXPECTATION_PICTURE_MAXIMUM_BYTES} bytes) "
            "the card shows"
        ),
    )


@dataclass(frozen=True)
class _AskedLine:
    """One `aco ask` write's result: the item, the fresh
    line's 1-based index, its `text`/`default`, and whichever card fields
    were given -- bundled so `_emit_ask_result` takes one value instead of
    five loose ones."""

    item: int
    index: int
    text: str
    default: str
    card: expectations.ExpectationCardFields


class _AskReason(StrEnum):
    """`aco ask`'s own `--json` `reason` vocabulary (`specs/ask.spec.md`):
    `asked` the only success."""

    ASKED = "asked"
    INVALID_ITEM = "invalid_item"
    INVALID_EXPECTATION = "invalid_expectation"
    INVALID_PICTURE = "invalid_picture"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _emit_ask_result(asked: _AskedLine, storage: body.Storage, *, as_json: bool) -> None:
    if as_json:
        card_fields = {key: value for key, value in asdict(asked.card).items() if value is not None}
        report.emit_json(
            True,
            _AskReason.ASKED,
            item=asked.item,
            index=asked.index,
            text=asked.text,
            default=asked.default,
            **card_fields,
        )
        return
    print(f"ASKED {workboard.item_label(asked.item, storage)} line {asked.index}: {asked.text}")


class _PictureFileError(protocol.ClaimError):
    """`_read_picture_file`'s own unreadable-file refusal,
    typed so `aco ask`'s `--json` can choose `invalid_picture` without
    parsing prose."""


def _read_picture_file(path: str) -> str:
    """`--picture FILE.svg`'s own filesystem boundary: read
    before any forge call, so a missing file refuses before the item body
    is even fetched. Content validation (size, `<svg>` root, no `<script>`,
    no external `href`) is `expectations.append_expectation`'s -- one owner, shared
    with the body parser's own defects."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise _PictureFileError(f"--picture {path} could not be read: {error}") from error


def _ask_expectation_reason(
    error: expectations.ExpectationTextError | expectations.ExpectationFieldError,
) -> _AskReason:
    """`run`'s own mapping from `append_expectation`'s two card-content
    refusals to their `--json` `reason`: a blank `--text`
    (`ExpectationTextError`) and a `--question`/`--example` failing its own
    rule both name `invalid_expectation`; only a refused `--picture`
    (`ExpectationFieldError` whose `field` is `picture`) names
    `invalid_picture`, per `specs/ask.spec.md`'s ASK-07/ASK-10 split."""
    if isinstance(error, expectations.ExpectationFieldError) and error.field == "picture":
        return _AskReason.INVALID_PICTURE
    return _AskReason.INVALID_EXPECTATION


def _append_expectation_card(parsed: argparse.Namespace, context: RunContext) -> int:
    """`ask`'s own work, every refusal raised by name for `run` to
    report: the picture file is read before the forge is ever resolved, so a
    missing one refuses before the item body is fetched."""
    picture = _read_picture_file(parsed.picture) if parsed.picture else None
    card = expectations.ExpectationCardFields(
        question=parsed.question, example=parsed.example, picture=picture
    )
    client = context.forge_writer
    number = int(parsed.item)
    current_body, config = cmd_rule.require_writable_target(client, context, number, command="ask")
    new_body = expectations.append_expectation(current_body, parsed.text, parsed.default, card=card)
    index = len(expectations.expectation_lines(new_body, storage=config.storage))
    client.update_item_body(number, new_body)
    asked = _AskedLine(
        item=number, index=index, text=parsed.text, default=parsed.default, card=card
    )
    _emit_ask_result(asked, config.storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`ask`'s own `--json` refusals, for the whole command and
    not only its first steps: the body write this command ends
    with can fail like any other forge call, and a failure there names this
    command's own `unavailable` rather than escaping the envelope."""
    as_json = parsed.json
    try:
        return _append_expectation_card(parsed, context)
    except _PictureFileError as error:
        return report.refuse(_AskReason.INVALID_PICTURE, error, as_json=as_json)
    except cmd_rule.InvalidTargetError as error:
        return report.refuse(_AskReason.INVALID_ITEM, error, as_json=as_json)
    except (expectations.ExpectationTextError, expectations.ExpectationFieldError) as error:
        return report.refuse(_ask_expectation_reason(error), error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_AskReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_AskReason.UNAVAILABLE, error, as_json=as_json)
