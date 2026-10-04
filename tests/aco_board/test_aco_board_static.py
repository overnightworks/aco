"""`static.py`'s containment and the real server's `/` and `/assets/**`.

`resolve_contained` is driven directly as the pure decision ("which file,
if any") it is; `asset`/`shell`/`ensure_built` add the filesystem read and
the committed build's own content types; the routing and guard-header
tests drive the real server, token-free, the way a browser loading the
shell does (`specs/aco-board.spec.md` ABRD-12).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aco_board_fixtures import FakeAcoRepository, serving

from aco_board import static
from aco_board.aco_cli import AcoCli
from aco_board.board import Boards
from aco_board.server import start_board


@pytest.fixture
def static_root(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    (root / "assets" / "index.js").write_text("console.log(1)", encoding="utf-8")
    return root


def test_resolve_contained_finds_a_real_file(static_root: Path) -> None:
    assert static.resolve_contained(static_root, "assets/index.js") == (
        static_root / "assets" / "index.js"
    )


@pytest.mark.parametrize(
    "relative_path",
    ["../index.html", "assets/../../index.html", "%2e%2e/index.html", "assets/%2e%2e%2findex.html"],
    ids=["literal-dotdot", "nested-dotdot", "encoded-dotdot", "encoded-dotdot-slash"],
)
def test_resolve_contained_refuses_a_path_that_climbs_out(
    static_root: Path, relative_path: str
) -> None:
    assert static.resolve_contained(static_root, relative_path) is None


def test_resolve_contained_refuses_a_symlinked_file(static_root: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.js"
    secret.write_text("outside", encoding="utf-8")
    (static_root / "assets" / "linked.js").symlink_to(secret)

    assert static.resolve_contained(static_root, "assets/linked.js") is None


def test_resolve_contained_refuses_a_symlinked_directory(static_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaked.js").write_text("outside", encoding="utf-8")
    (static_root / "assets" / "alias").symlink_to(outside, target_is_directory=True)

    assert static.resolve_contained(static_root, "assets/alias/leaked.js") is None


def test_resolve_contained_refuses_a_missing_file(static_root: Path) -> None:
    assert static.resolve_contained(static_root, "assets/missing.js") is None


def test_resolve_contained_refuses_a_directory(static_root: Path) -> None:
    assert static.resolve_contained(static_root, "assets") is None


def test_asset_refuses_an_unrecognized_extension(static_root: Path) -> None:
    (static_root / "assets" / "notes.txt").write_text("plain text", encoding="utf-8")

    assert static.asset("/assets/notes.txt", static_root) is None


def test_asset_reads_a_recognized_file_with_its_content_type(static_root: Path) -> None:
    served = static.asset("/assets/index.js", static_root)

    assert served is not None
    assert served.content == b"console.log(1)"
    assert served.content_type == "text/javascript; charset=utf-8"


def test_shell_reads_the_committed_index_html(static_root: Path) -> None:
    served = static.shell(static_root)

    assert served.content == b"<html>shell</html>"
    assert served.content_type == "text/html; charset=utf-8"


def test_ensure_built_passes_once_the_shell_exists(static_root: Path) -> None:
    static.ensure_built(static_root)


def test_ensure_built_names_the_missing_shell_clearly(tmp_path: Path) -> None:
    empty_root = tmp_path / "unbuilt"
    empty_root.mkdir()

    with pytest.raises(static.StaticAssetsMissingError, match=r"index\.html"):
        static.ensure_built(empty_root)


def test_start_board_refuses_to_bind_once_the_shell_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(static, "STATIC_ROOT", tmp_path / "unbuilt")

    with pytest.raises(static.StaticAssetsMissingError):
        start_board(0, Boards({}))


def test_the_shell_and_its_assets_need_no_token(
    repository: FakeAcoRepository,
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        shell = board.get_shell()
        asset = board.call_api("GET", "/assets/index.js", presented=None)

    assert shell.status == 200
    assert shell.headers["Content-Type"] == "text/html; charset=utf-8"
    assert asset.status == 200
    assert asset.headers["Content-Type"] == "text/javascript; charset=utf-8"


def test_a_missing_asset_and_an_unknown_path_both_answer_404(
    repository: FakeAcoRepository,
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        missing_asset = board.call_api("GET", "/assets/missing.js", presented=None)
        traversal = board.call_api("GET", "/assets/../server.py", presented=None)
        unknown_path = board.call_api("GET", "/elsewhere", presented=None)

    assert missing_asset.status == 404
    assert traversal.status == 404
    assert unknown_path.status == 404


@pytest.mark.parametrize("path", ["/", "/assets/index.js"], ids=["shell", "asset"])
def test_a_method_the_shell_or_an_asset_does_not_serve_is_refused(
    repository: FakeAcoRepository, path: str
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("PUT", path, presented=None)

    assert response.status == 405
    assert response.headers["Allow"] == "GET"


@pytest.mark.parametrize("path", ["/", "/assets/index.js"], ids=["shell", "asset"])
def test_posting_to_the_shell_or_an_asset_path_is_not_found(
    repository: FakeAcoRepository, path: str
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("POST", path, presented=None)

    assert response.status == 404


def test_every_shell_and_asset_answer_carries_the_guard_headers(
    repository: FakeAcoRepository,
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        shell = board.get_shell()

    assert shell.headers["Cache-Control"] == "no-store"
    assert shell.headers["Referrer-Policy"] == "no-referrer"
    policy = shell.content_security_policy or ""
    assert "script-src 'self'" in policy
    assert "'nonce-" not in policy
    assert not any(name.lower().startswith("access-control-") for name in shell.headers)
