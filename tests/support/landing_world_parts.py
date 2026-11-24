"""Parts a landing world is assembled from: the forge's file listing, the merge observer and the
land command with a lane record."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import pull_request_listing
from lane_record_fixtures import approving_record_file
from store_fixtures import lineage_observation

from aco import forge
from aco.workboard import MergeMethod

if TYPE_CHECKING:
    from github_fixtures import FakeForge


def landing_listing(head: str, *paths: str) -> forge.PullRequestChanges:
    """What the forge lists for a landing that changes `paths` at `head`."""
    return pull_request_listing(head, *(forge.ChangedFile(path, None) for path in paths))


def land_command_with_record(directory: Path, head: str) -> list[str]:
    """`aco land` of pull request 12 at `head`, with a lane record file in `directory` approving
    it, for a lane whose claim stores no run."""
    record = approving_record_file(directory, head)
    return ["--repo", REPOSITORY, "land", "12", "--head", head, "--record", str(record)]


def observe_merge_entry(
    monkeypatch: pytest.MonkeyPatch, client: FakeForge, clone: Path
) -> list[tuple[object, object]]:
    """The claim-state lineage `clone` shows at each merge `client` is asked for."""
    entry: list[tuple[object, object]] = []
    merge = client.merge_landing

    def observe_entry(
        number: int, *, head_sha: str, method: MergeMethod, title: str, body: str
    ) -> str:
        entry.append(lineage_observation(clone))
        return merge(number, head_sha=head_sha, method=method, title=title, body=body)

    monkeypatch.setattr(client, "merge_landing", observe_entry)
    return entry
