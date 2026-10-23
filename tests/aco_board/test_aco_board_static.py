"""`static.py`'s containment and the real server's `/` and `/assets/**`.

`resolve_contained` is driven directly as the pure decision ("which file,
if any") it is; `asset`/`shell`/`ensure_built` add the filesystem read and
the committed build's own content types; the routing and guard-header
tests drive the real server, token-free, the way a browser loading the
shell does (`specs/serve.spec.md` ABRD-12).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from aco_board_fixtures import FakeAcoRepository, serving

from aco.board import static
from aco.board.aco_cli import AcoCli
from aco.board.board import Boards
from aco.board.server import start_board


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


def _escaping_literal(relative_path: str) -> Callable[[Path, Path], tuple[Path, str]]:
    """A request path that tries to escape `static_root` without touching the
    filesystem -- every variant still ends up refused as "missing", never as
    a resolved file outside the root."""

    def arrange(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
        del tmp_path
        return static_root, relative_path

    return arrange


def _via_a_symlinked_file(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    secret = tmp_path / "secret.js"
    secret.write_text("outside", encoding="utf-8")
    (static_root / "assets" / "linked.js").symlink_to(secret)
    return static_root, "assets/linked.js"


def _via_a_symlinked_directory(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leaked.js").write_text("outside", encoding="utf-8")
    (static_root / "assets" / "alias").symlink_to(outside, target_is_directory=True)
    return static_root, "assets/alias/leaked.js"


def _via_a_symlinked_root(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    """The root passed to `resolve_contained` (`static/assets` in production,
    `static.py:66`) is itself a symlink: every file under it would otherwise
    resolve as "contained" against wherever that symlink points."""
    del static_root
    real_assets = tmp_path / "real-assets"
    real_assets.mkdir()
    (real_assets / "index.js").write_text("console.log(1)", encoding="utf-8")
    symlinked_root = tmp_path / "assets-alias"
    symlinked_root.symlink_to(real_assets, target_is_directory=True)
    return symlinked_root, "index.js"


def _a_missing_file(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    del tmp_path
    return static_root, "assets/missing.js"


def _a_directory_itself(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    del tmp_path
    return static_root, "assets"


def _a_missing_root(static_root: Path, tmp_path: Path) -> tuple[Path, str]:
    del static_root
    return tmp_path / "does-not-exist", "index.html"


@pytest.mark.parametrize(
    "arrange",
    [
        _escaping_literal("../index.html"),
        _escaping_literal("assets/../../index.html"),
        _escaping_literal("%2e%2e/index.html"),
        _escaping_literal("assets/%2e%2e%2findex.html"),
        _escaping_literal("assets/%252e%252e/index.html"),
        _escaping_literal("assets\\..\\..\\index.html"),
        _escaping_literal("/etc/passwd"),
        _escaping_literal("assets/ind\x00ex.html"),
        _via_a_symlinked_file,
        _via_a_symlinked_directory,
        _via_a_symlinked_root,
        _a_missing_file,
        _a_directory_itself,
        _a_missing_root,
    ],
    ids=[
        "literal-dotdot",
        "nested-dotdot",
        "encoded-dotdot",
        "encoded-dotdot-slash",
        "double-encoded-dotdot",
        "backslash-not-a-separator",
        "absolute-path-stays-relative",
        "nul-byte",
        "symlinked-file",
        "symlinked-directory",
        "symlinked-root",
        "missing-file",
        "a-directory-itself",
        "missing-root",
    ],
)
def test_resolve_contained_refuses_an_unservable_path(
    static_root: Path,
    tmp_path: Path,
    arrange: Callable[[Path, Path], tuple[Path, str]],
) -> None:
    root, relative_path = arrange(static_root, tmp_path)

    assert static.resolve_contained(root, relative_path) is None


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
    boards = Boards({})

    with pytest.raises(static.StaticAssetsMissingError):
        start_board(0, boards)


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html; charset=utf-8"),
        ("/assets/index.js", "text/javascript; charset=utf-8"),
        ("/assets/index.js?v=1", "text/javascript; charset=utf-8"),
        ("/assets/index.js#ignored", "text/javascript; charset=utf-8"),
    ],
    ids=["shell", "asset", "asset-with-query", "asset-with-fragment"],
)
def test_the_shell_and_its_assets_need_no_token(
    repository: FakeAcoRepository, path: str, content_type: str
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("GET", path, presented=None)

    assert response.status == 200
    assert response.headers["Content-Type"] == content_type


@pytest.mark.parametrize(
    "path",
    ["/assets/missing.js", "/assets/../server.py", "/elsewhere", "/assets/", "/assets"],
    ids=[
        "missing-asset",
        "traversal",
        "unknown-path",
        "assets-directory-with-slash",
        "assets-directory-without-slash",
    ],
)
def test_an_unservable_path_answers_404(repository: FakeAcoRepository, path: str) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("GET", path, presented=None)

    assert response.status == 404


def test_posting_to_an_unknown_path_answers_404(repository: FakeAcoRepository) -> None:
    """Unlike `/` and `/assets/**`, a path the board does not route at all stays
    a `404` for POST too: only the shell and the assets have a real `GET`-only
    route to refuse with `405` (server.py's `do_POST` fallback)."""
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("POST", "/elsewhere", presented=None)

    assert response.status == 404


@pytest.mark.parametrize("path", ["/", "/assets/index.js"], ids=["shell", "asset"])
@pytest.mark.parametrize("method", ["PUT", "POST", "HEAD"])
def test_a_method_the_shell_or_an_asset_does_not_serve_is_refused(
    repository: FakeAcoRepository, method: str, path: str
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api(method, path, presented=None)

    assert response.status == 405
    assert response.headers["Allow"] == "GET"


@pytest.mark.parametrize("path", ["/", "/assets/index.js"], ids=["shell", "asset"])
def test_every_shell_and_asset_answer_carries_the_guard_headers(
    repository: FakeAcoRepository, path: str
) -> None:
    with serving(AcoCli(directory=repository.directory)) as board:
        response = board.call_api("GET", path, presented=None)

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    policy = response.content_security_policy or ""
    assert "script-src 'self'" in policy
    assert "img-src data:" in policy
    assert "'nonce-" not in policy
    assert not any(name.lower().startswith("access-control-") for name in response.headers)
