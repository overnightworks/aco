import pytest

from aco import forge, github_body_write
from aco.protocol import ClaimError


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        pytest.param(forge.ForgePermissionDeniedError("HTTP 403"), "REFUSED", id="W1-permission"),
        pytest.param(forge.ForgeNotFoundError("HTTP 404"), "REFUSED", id="W3-not-found"),
        pytest.param(
            ClaimError("gh is required for issue claims"), "REFUSED", id="W4-gh-never-ran"
        ),
        pytest.param(forge.ForgeTransientError("timeout"), "UNKNOWN", id="W5-transient"),
        pytest.param(
            forge.ForgeMalformedResponseError("not json"), "UNKNOWN", id="W7-malformed-response"
        ),
        pytest.param(forge.ForgeError("HTTP 500"), "UNKNOWN", id="W8-unclassified"),
    ],
)
def test_a_failed_body_write_is_refused_only_when_nothing_was_written(
    error: ClaimError, outcome: str
) -> None:
    """Spec: ADOPT-24, ADOPT-25 -- a refusal the forge gave before writing, or a `gh` that
    never ran, wrote nothing; every other failure may have written."""
    assert (
        github_body_write.body_write_outcome(error) is github_body_write.BodyWriteOutcome[outcome]
    )
