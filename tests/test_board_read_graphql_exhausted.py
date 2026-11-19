"""A board read and `aco check <pull request>` need no GraphQL point: with every GraphQL call
refused, both still answer. The GitHub CLI is the only fake."""

import json
import os
import sys
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from check_pull_request_fixtures import LANE_BRANCH, LANE_CLAIM
from cli_fixtures import freeze_cli_now, run_cli
from github_pages import api_head, api_pull_request
from rate_limit_fixtures import GRAPHQL_REFUSAL
from store_fixtures import publish_claims_from_a_second_clone

# Answers a REST route (a request's path with the issue state it filters on) with the JSON its
# `FAKE_GH_ROUTES` file holds, through the request's own `--jq` filter as `gh` does; refuses a
# GraphQL or `pr` call, noting its arguments in `FAKE_GH_REFUSED`.
FAKE_GH = """#!{python}
import json, os, subprocess, sys
from urllib.parse import parse_qs, urlsplit

arguments = sys.argv[1:]
if arguments[:2] == ["api", "graphql"] or arguments[0] == "pr":
    with open(os.environ["FAKE_GH_REFUSED"], "a") as refused:
        refused.write(" ".join(arguments) + "\\n")
    print(os.environ["FAKE_GH_REFUSAL"], file=sys.stderr)
    sys.exit(1)
location = urlsplit(next(argument for argument in arguments if argument.startswith("repos/")))
states = parse_qs(location.query).get("state")
route = location.path if states is None else f"{{location.path}}?state={{states[0]}}"
with open(os.environ["FAKE_GH_ROUTES"]) as routes_file:
    routes = json.load(routes_file)
if route not in routes:
    print(f"unexpected request: {{arguments}}", file=sys.stderr)
    sys.exit(1)
answer = json.dumps(routes[route])
if "--jq" in arguments:
    answer = subprocess.run(
        ["jq", "-cr", arguments[arguments.index("--jq") + 1]],
        input=answer, capture_output=True, text=True, check=True,
    ).stdout.strip()
print(answer)
"""
ITEM = 90
ISSUES = f"repos/{REPOSITORY}/issues"
PULLS = f"repos/{REPOSITORY}/pulls"
DECLARING_MERGE = {
    "number": 140,
    "title": "Lands it",
    "body": f"Work-Item: #{ITEM}\n\nCloses #{ITEM}",
    "pull_request": {"merged_at": "2026-08-20T12:00:00Z"},
}
OPEN_ITEM = {
    "number": ITEM,
    "title": "Landed but open",
    "body": complete_contract("Close it."),
    "labels": [],
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-20T00:00:00Z",
    "author_association": "MEMBER",
}
LANE_BODY = "No-Item: docs\n\nTidy the README."
CHECKED_PULL_REQUEST = api_pull_request(
    body=LANE_BODY,
    head=api_head(ref=LANE_BRANCH),
    merged_at=None,
    merge_commit_sha="b" * 40,
    changed_files=1,
)


def serve_rest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rest: dict[str, object]) -> Path:
    """A `gh` on `PATH` answering each REST route of `rest` and refusing every GraphQL and `pr`
    call with the recorded rate-limit text; returns the file listing what it refused."""
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    routes = tmp_path / "gh-routes.json"
    routes.write_text(json.dumps(rest))
    refused = tmp_path / "gh-refused"
    refused.touch()
    fake_gh = shims / "gh"
    fake_gh.write_text(FAKE_GH.format(python=sys.executable))
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_ROUTES", str(routes))
    monkeypatch.setenv("FAKE_GH_REFUSED", str(refused))
    monkeypatch.setenv("FAKE_GH_REFUSAL", GRAPHQL_REFUSAL)
    return refused


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


def test_a_board_read_with_a_recovery_candidate_succeeds_while_graphql_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = serve_rest(
        monkeypatch,
        tmp_path,
        {
            f"{ISSUES}?state=open": [OPEN_ITEM],
            f"{ISSUES}?state=closed": [DECLARING_MERGE],
            f"{PULLS}?state=open": [],
            f"{ISSUES}/{ITEM}/events": [{"event": "closed", "created_at": "2026-08-20T12:00:01Z"}],
        },
    )

    result = run_cli(["board", "--json"], capsys)

    payload = json.loads(result.stdout)
    assert (
        result.status,
        [row["number"] for row in payload["recovery"]],
        refused.read_text(),
    ) == (0, [ITEM], "")


def test_a_pull_request_check_succeeds_while_graphql_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    publish_claims_from_a_second_clone(github_clone, bare_remote, (LANE_CLAIM,))
    landing_issue = {"state": "open", "title": "Tidy", "body": LANE_BODY, "pull_request": {}}
    refused = serve_rest(
        monkeypatch,
        tmp_path,
        {
            f"repos/{REPOSITORY}": {"default_branch": "main"},
            f"{ISSUES}/12": landing_issue,
            f"{PULLS}/12": CHECKED_PULL_REQUEST,
            f"{PULLS}/12/files": [{"filename": "README.md", "status": "modified"}],
        },
    )

    result = run_cli(["check", "12"], capsys)

    assert (result.status, result.stdout, refused.read_text()) == (
        0,
        "PR #12 by ada declares No-Item: docs\n",
        "",
    )
