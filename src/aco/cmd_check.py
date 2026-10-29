"""The `check` command (`specs/check.spec.md`)."""
# ruff: noqa: T201 - the check command writes its result lines to stdout

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Literal, cast

from . import board_read, body, checkout, forge, policy, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext

STDIN_SUBJECT = "-"
_STDIN_CARRIES_NO_BODY = "check - needs the body on stdin: aco check - < body.md"


class CheckInput(Enum):
    """The one non-reference subject `check` reads: a body piped on stdin. A
    plain `Enum` member, never a `str`, because `run` tells a trunk commit
    from every other subject by `isinstance(..., str)`."""

    STDIN = STDIN_SUBJECT


def _checked_classification(
    context: policy.LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
) -> workboard.Classification | workboard.ClassificationDefect:
    classification = policy.structural_classification(context, detail)
    if isinstance(classification, workboard.ClassificationDefect):
        return classification
    defect = policy.classification_defect(
        context, claims, detail, classification, expected_head=detail.head_sha
    )
    return classification if defect is None else defect


class _CheckKind(StrEnum):
    """Which subject one `check` run read -- the `--json` discriminator.

    The number space holds three of them, because that is what the one
    dispatch request actually distinguishes: GitHub gives issues and pull
    requests a single number space, so a number that is not there was never
    proven to be either. A trunk commit is the fourth: named by its `sha`,
    read from local history instead of that number space.
    """

    PULL_REQUEST = "pull_request"
    ISSUE = "issue"
    MISSING = "missing"
    TRUNK_COMMIT = "trunk_commit"


@dataclass(frozen=True)
class _NumberSubject:
    """One run's subject in the forge's number space, printed under
    `number`. Its `kind` cannot be `TRUNK_COMMIT`: the key travels with the
    value that determines it, so no answer can name a sha under `number`."""

    kind: Literal[_CheckKind.PULL_REQUEST, _CheckKind.ISSUE, _CheckKind.MISSING]
    number: int

    def payload(self) -> dict[str, object]:
        return {"kind": self.kind.value, "number": self.number}


@dataclass(frozen=True)
class _TrunkSubject:
    """One run's subject in local trunk history, printed under `sha`. It
    carries no `kind` field, because a commit is never anything but
    `TRUNK_COMMIT`."""

    sha: str

    def payload(self) -> dict[str, object]:
        return {"kind": _CheckKind.TRUNK_COMMIT.value, "sha": self.sha}


_CheckSubject = _NumberSubject | _TrunkSubject


class _CheckReason(StrEnum):
    """`aco check`'s own `--json` `reason` vocabulary (`specs/check.spec.md`):
    `valid` the only exit `0`; `blocked` the only exit `3`
    (a valid, complete issue with an open dependency); every other member
    exits `2`. `valid`/`malformed`/`incomplete` mirror
    `body.BodyShapeVerdict`'s own three values -- the body-shape decision
    `check` and `check -` both read, never re-derived from a defect
    sentence's own prefix. `not_on_trunk` is the trunk form's own member: a
    commit the first-parent walk does not hold may well exist in this
    repository, so it is never `missing`."""

    VALID = body.BodyShapeVerdict.VALID.value
    BLOCKED = "blocked"
    MALFORMED = body.BodyShapeVerdict.MALFORMED.value
    INCOMPLETE = body.BodyShapeVerdict.INCOMPLETE.value
    INVALID_CLASSIFICATION = "invalid_classification"
    MISSING = "missing"
    NOT_ON_TRUNK = "not_on_trunk"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _CheckOutcome:
    """One `check` answer: the line a human reads, and the `--json` `reason`
    a caller acts on. `subject` is the number or the trunk commit the run
    was asked about, printing itself under its own key; `message` mirrors
    the line's own finding without its `ISSUE #<n> `/`REFUSED: #<n> `/
    `REFUSED: <sha> ` prefix; `blocked_by` is only ever set together with
    `_CheckReason.BLOCKED`."""

    subject: _CheckSubject
    line: str
    reason: _CheckReason
    message: str | None = None
    blocked_by: tuple[str, ...] = ()

    def exit_code(self) -> int:
        if self.reason is _CheckReason.VALID:
            return 0
        if self.reason is _CheckReason.BLOCKED:
            return 3
        return 2

    def report(self, *, as_json: bool) -> int:
        if as_json:
            payload = self.subject.payload()
            if self.blocked_by:
                payload["blocked_by"] = list(self.blocked_by)
            if self.message is not None:
                payload["message"] = self.message
            report.emit_json(self.reason is _CheckReason.VALID, self.reason, **payload)
        else:
            print(self.line, file=sys.stderr if self.message is not None else sys.stdout)
        return self.exit_code()


def _pull_request_check(
    run: RunContext,
    claims: tuple[protocol.ActiveClaim, ...],
    repository: str,
    number: int,
    storage: body.Storage,
) -> _CheckOutcome:
    detail = run.forge.landing(number)
    context = policy.LandingCheckContext(run, repository, storage)
    checked = _checked_classification(context, claims, detail)
    if isinstance(checked, workboard.ClassificationDefect):
        return _CheckOutcome(
            _NumberSubject(_CheckKind.PULL_REQUEST, detail.number),
            f"REFUSED: pull request #{detail.number} {checked.message}",
            _CheckReason.INVALID_CLASSIFICATION,
            checked.message,
        )
    return _CheckOutcome(
        _NumberSubject(_CheckKind.PULL_REQUEST, detail.number),
        workboard.pull_request_declaration(detail.number, detail.author, checked),
        _CheckReason.VALID,
    )


def _missing_number(repository: str, number: int, storage: body.Storage) -> _CheckOutcome:
    """A number neither mode can read, named without claiming which of the
    two it would have been."""
    finding = f"does not exist in {repository}"
    return _CheckOutcome(
        _NumberSubject(_CheckKind.MISSING, number),
        f"REFUSED: {workboard.item_label(number, storage)} {finding}",
        _CheckReason.MISSING,
        finding,
    )


def _issue_line(number: int, finding: str, storage: body.Storage) -> str:
    """The one shape every issue-mode answer takes."""
    return f"ISSUE {workboard.item_label(number, storage)} {finding}"


def _refused_issue(
    number: int,
    finding: str,
    reason: _CheckReason,
    storage: body.Storage,
    *,
    blocked_by: tuple[str, ...] = (),
) -> _CheckOutcome:
    return _CheckOutcome(
        _NumberSubject(_CheckKind.ISSUE, number),
        _issue_line(number, finding, storage),
        reason,
        finding,
        blocked_by,
    )


def _issue_check(
    client: forge.ForgeReader,
    repository: str,
    raw_body: str,
    number: int,
    *,
    storage: body.Storage,
) -> _CheckOutcome:
    """Whether this issue's body is the contract a builder can start from:
    readable, complete, and unblocked. Its dependencies come from GitHub's
    own `blocked_by` relation, or the state-ref item's own `[record]` table
    under `storage = "state-ref"` -- a body never states them itself."""
    shape = body.body_shape_check(raw_body, storage=storage)
    if shape.defects:
        return _refused_issue(number, shape.defects[0], _CheckReason(shape.verdict.value), storage)
    blockers = workboard.open_dependency_blockers(
        client.list_board_dependencies(number), repository
    )
    if blockers:
        labels = tuple(
            workboard.open_blocker_label(blocker, repository, storage) for blocker in blockers
        )
        return _refused_issue(
            number,
            f"blocked by {', '.join(labels)}",
            _CheckReason.BLOCKED,
            storage,
            blocked_by=labels,
        )
    return _CheckOutcome(
        _NumberSubject(_CheckKind.ISSUE, number),
        _issue_line(number, "body ok", storage),
        _CheckReason.VALID,
    )


def _body_check_report(check: body.BodyShapeCheck, *, as_json: bool) -> int:
    """The one rendering of a `check -` answer: `body.body_shape_check`'s
    own sentences, never truncated to the first, since there is no live
    item here to refuse a single verdict about."""
    ok = check.verdict is body.BodyShapeVerdict.VALID
    if as_json:
        report.emit_json(ok, _CheckReason(check.verdict.value), defects=list(check.defects))
    elif check.defects:
        for defect in check.defects:
            print(defect, file=sys.stderr)
    else:
        print("body ok")
    return 0 if ok else 2


def _check_piped_body(parsed: argparse.Namespace, context: RunContext) -> int:
    """`check -` is forge-free, the same way `status` and `bootstrap` are: it
    reads stdin only, never an issue, a live claim, a filesystem path, or the
    forge's own `blocked_by` relation, so it never asks the `RunContext` for
    its forge. It still reads the repository's own storage pin: `[record]` is
    a known key under `storage = "state-ref"` and an unknown one under
    `storage = "github"`, the same gate `session._state_ref_forge`'s own items
    already read through `state_board._decode_item`. A stdin that carries no
    body (an idle harness socket, a terminal, `/dev/null`) is refused after
    the pin and before any read, so the command never waits on it (CHECK-24)."""
    storage = context.config.storage
    if not report.stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(_STDIN_CARRIES_NO_BODY)
    check = body.body_shape_check(report.read_piped_body(), storage=storage)
    return _body_check_report(check, as_json=parsed.json)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """One number or trunk commit, one dispatch request into one of four
    answers: a pull request to classify, an issue whose body contract to
    read, a trunk commit to classify from its own trailer block
    (LAND-48), or a number that is in neither number space. Only the
    pull-request side needs the live claims, so the issue side never
    fetches the state ref. `-` is a fifth: a body piped on stdin, judged
    without any read of the forge."""
    as_json = parsed.json
    try:
        if parsed.number is CheckInput.STDIN:
            return _check_piped_body(parsed, context)
        if isinstance(parsed.number, str):
            return _check_trunk_commit(parsed, context)
        number = int(parsed.number)
        client = context.forge
        # Every forge read (the reference itself, the PR/issue body it
        # dispatches to) stays inside this handler, so a forge failure
        # anywhere on the check path reports `unavailable` through the
        # shared envelope rather than the plain sentence alone.
        config = context.config
        repository = client.repository.path
        reference = client.item_reference(number)
        if reference.state is forge.ItemState.MISSING:
            outcome = _missing_number(repository, number, config.storage)
        elif reference.is_landing:
            outcome = _pull_request_check(
                context,
                tuple(context.observation.claims.values()),
                repository,
                number,
                config.storage,
            )
        else:
            outcome = _issue_check(
                client, repository, reference.body or "", number, storage=config.storage
            )
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_CheckReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_CheckReason.UNAVAILABLE, error, as_json=as_json)
    return outcome.report(as_json=as_json)


def _trunk_classification_text(
    classification: workboard.TrunkClassification, storage: body.Storage
) -> str:
    """`classification`'s own display line, the trunk-trailer counterpart of
    `workboard.WorkItemClassification`/`workboard.NoItemClassification`'s `__str__`: a trunk
    `Work-Item:` trailer names bare, repository-local
    numbers (`workboard.TrunkWorkItemClassification.numbers`), never a qualified
    `workboard.IssueReference` -- a commit's own trailer is always local -- so this
    lives here rather than reusing either PR-body type's `__str__`."""
    if isinstance(classification, workboard.NoItemClassification):
        return f"No-Item: {classification.kind.value}"
    return "Work-Item: " + ", ".join(
        workboard.item_label(number, storage) for number in classification.numbers
    )


def _refused_trunk_commit(sha: str, finding: str, reason: _CheckReason) -> _CheckOutcome:
    return _CheckOutcome(_TrunkSubject(sha), f"REFUSED: {sha} {finding}", reason, finding)


_STATE_REF_TRAILER_PAST_THE_ID_SPACE = (
    "carries `Work-Item:` {number}, which " + workboard.NAMES_NO_ITEM
)


def _trailer_number_past_the_id_space(
    classification: workboard.TrunkClassification, storage: body.Storage
) -> int | None:
    """LAND-68: under `storage = "state-ref"` a
    trailer number past `aco-ffffff` names no item, and its label would be
    an id `workboard.parse_item_reference` refuses back -- the first such
    number, or `None` when every number names an item."""
    if not isinstance(classification, workboard.TrunkWorkItemClassification):
        return None
    return next(
        (number for number in classification.numbers if workboard.names_no_item(number, storage)),
        None,
    )


def _trunk_commit_outcome(
    sha: str, landing: checkout.TrunkLanding | None, storage: body.Storage
) -> _CheckOutcome:
    """`sha`'s own answer (LAND-48): the same three answers
    `check <pr>` reads from a pull request body's classification
    (LAND-04/LAND-06), read instead from the trailer block of `landing`, the
    walked first-parent trunk's own entry for `sha` -- `None` when that walk
    holds no such commit at all."""
    if landing is None:
        return _refused_trunk_commit(
            sha, checkout.SHA_NOT_ON_TRUNK_DEFECT, _CheckReason.NOT_ON_TRUNK
        )
    classification = landing.classification
    if classification is None:
        return _refused_trunk_commit(
            sha,
            "carries no `Work-Item:` or `No-Item:` trailer",
            _CheckReason.INVALID_CLASSIFICATION,
        )
    if isinstance(classification, workboard.ClassificationDefect):
        return _refused_trunk_commit(
            sha, classification.message, _CheckReason.INVALID_CLASSIFICATION
        )
    past = _trailer_number_past_the_id_space(classification, storage)
    if past is not None:
        return _refused_trunk_commit(
            sha,
            _STATE_REF_TRAILER_PAST_THE_ID_SPACE.format(number=past),
            _CheckReason.INVALID_CLASSIFICATION,
        )
    return _CheckOutcome(
        _TrunkSubject(sha),
        f"{sha} declares {_trunk_classification_text(classification, storage)}",
        _CheckReason.VALID,
    )


def _check_trunk_commit(parsed: argparse.Namespace, context: RunContext) -> int:
    """`check <sha>`: the trunk form of the one check, reporting through the
    same envelope and the same exit codes the number forms use.
    Its walk is the one `release --merged <sha>` verifies against under
    `storage = "state-ref"` (LAND-47/LAND-52), reused rather than re-derived
    here. Needs no forge at all: a trunk commit's trailer is local history."""
    sha = cast(str, parsed.number)
    landings = checkout.trunk_landings(
        context.trunk_ref, board_read.TRUNK_LANDING_DEPTH, directory=context.toplevel
    )
    landing = next((entry for entry in landings if entry.sha == sha), None)
    return _trunk_commit_outcome(sha, landing, context.config.storage).report(as_json=parsed.json)
