"""The GitHub adapter's pinned merge call: which failure of the merge endpoint means what."""

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import MERGE_COMMIT_SHA

from aco import forge, github, workboard


@pytest.mark.parametrize(
    ("message", "refusal"),
    [
        pytest.param(
            "gh: merge not possible (HTTP 409)", forge.ForgeMergeConflictError, id="head-moved"
        ),
        pytest.param(
            "gh: merge not possible (HTTP 405)", forge.ForgeMergeRefusedError, id="merge-refused"
        ),
        pytest.param(
            "gh: Merge already in progress (HTTP 405)",
            forge.ForgeMergeInProgressError,
            id="merge-already-in-progress",
        ),
        pytest.param(
            "gh: Server Error (HTTP 502)", forge.ForgeMergeUnansweredError, id="server-error"
        ),
    ],
)
def test_github_adapter_tells_a_moved_head_from_a_refused_or_pending_merge(
    message: str, refusal: type[forge.ForgeError]
) -> None:
    """A 409 from the merge endpoint means the pull request's
    head moved since `landing_readiness` read it -- `ForgeMergeConflictError`,
    whose recovery is a re-run. GitHub's REST reference reads a 405 as "merge
    cannot be performed" -- `ForgeMergeRefusedError`, carrying the
    forge's own message, since no re-run repairs it; a 405 saying the merge is
    already in progress (`ForgeMergeInProgressError`) and any 5xx
    (`ForgeMergeUnansweredError`) leave the merge pending."""
    client = github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: (_ for _ in ()).throw(forge.ForgeError(message)),
    )

    with pytest.raises(refusal) as raised:
        client.merge_landing(
            57,
            head_sha=MERGE_COMMIT_SHA,
            method=workboard.MergeMethod.MERGE,
            title="t",
            body="Work-Item: #42\n",
        )

    assert str(raised.value) == message
