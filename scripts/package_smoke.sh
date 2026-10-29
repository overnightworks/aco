#!/usr/bin/env bash
# Package smoke: build the sdist, the wheel built from it and a working-tree wheel,
# each carrying exactly the tracked aco package (git ls-files src/aco), with no Node on PATH.
# CI's `package` job and release.yml both run it, so the release uploads only
# distributions this script has proven.
#
# Usage: scripts/package_smoke.sh [OUT_DIR]
#   OUT_DIR receives the built distributions (default: a temporary directory);
#   it must be empty or absent so every check reads the build it just made.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
serve_pid=""
trap '[[ -n "$serve_pid" ]] && kill "$serve_pid" 2>/dev/null; rm -rf "$scratch"' EXIT
out_dir="${1:-$scratch/dist}"

if [[ -n "$(ls -A "$out_dir" 2>/dev/null)" ]]; then
    echo "ERROR: $out_dir is not empty; the smoke must check only its own build" >&2
    exit 1
fi
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

# The committed package tree is the manifest every archive must match exactly; a
# file that exists only in the working tree (a module deleted since an earlier
# build, a stray build output, a sourcemap) would otherwise ship unproven, and a
# committed file an ignore rule hides would go missing. Read before the narrowed
# PATH hides git.
expected_package="$scratch/expected-package"
git -C "$repository_root" ls-files -- src/aco | sed 's|^src/||' | sort >"$expected_package"

# A PATH holding only the tools this script needs proves the install path never
# reaches for Node, which a developer machine or CI runner usually has.
# UV_PYTHON pins the interpreter found now, before the narrowed PATH hides it.
UV_PYTHON="$(uv python find)"
export UV_PYTHON
tool_path="$scratch/path"
mkdir -p "$tool_path"
for tool in uv unzip tar gzip grep sed sort diff rm sleep head cat; do
    ln -s "$(command -v "$tool")" "$tool_path/$tool"
done
export PATH="$tool_path"
if command -v node >/dev/null; then
    echo "ERROR: node is still reachable on the narrowed PATH" >&2
    exit 1
fi

uv build --quiet --out-dir "$out_dir" "$repository_root"
# `uv tool install --from .` builds its wheel from the working tree, not from the
# sdist, so that path is proven on its own build.
tree_wheel_dir="$scratch/tree-wheel"
uv build --quiet --wheel --out-dir "$tree_wheel_dir" "$repository_root"

# The release uploads every distribution in OUT_DIR, so it must hold exactly
# the one wheel and one sdist proven below.
shopt -s nullglob
distributions=("$out_dir"/*)
wheels=("$out_dir"/*.whl)
sdists=("$out_dir"/*.tar.gz)
tree_wheels=("$tree_wheel_dir"/*.whl)
shopt -u nullglob
if ((${#wheels[@]} != 1 || ${#sdists[@]} != 1 || ${#distributions[@]} != 2)); then
    echo "ERROR: $out_dir must hold exactly one wheel and one sdist, found:" >&2
    printf '  %s\n' "${distributions[@]##*/}" >&2
    exit 1
fi
if ((${#tree_wheels[@]} != 1)); then
    echo "ERROR: $tree_wheel_dir must hold exactly one wheel, found ${#tree_wheels[@]}" >&2
    exit 1
fi
wheel="${wheels[0]}"
sdist="${sdists[0]}"
tree_wheel="${tree_wheels[0]}"

# Listings are read whole before grep: `lister | grep -q` lets grep close the
# pipe early, and pipefail would report the lister's SIGPIPE as a missing file.
wheel_listing="$(unzip -Z1 "$wheel")"
sdist_listing="$(tar tzf "$sdist")"

# Frontend sources, node_modules and sourcemaps never ship, wherever they sit.
check_no_build_inputs() {
    local archive="$1" listing="$2" forbidden
    forbidden="$(grep -E '(^|/)(frontend|node_modules)/|\.map$' <<<"$listing" || true)"
    if [[ -n "$forbidden" ]]; then
        echo "ERROR: $archive carries build inputs:" >&2
        sed 's/^/  /' <<<"$forbidden" >&2
        exit 1
    fi
}

# Compares an archive's package files, relative to the directory holding aco/,
# with the committed manifest and names every missing or extra file.
check_package_manifest() {
    local archive="$1" listing="$2" package_prefix="$3" shipped
    shipped="$(grep -E "^${package_prefix}aco/" <<<"$listing" | grep -v '/$' \
        | sed -E "s|^${package_prefix}||" | sort || true)"
    if ! diff -u --label committed --label "$archive" "$expected_package" - <<<"$shipped" >&2; then
        echo "ERROR: $archive package files differ from git ls-files src/aco (see diff above)" >&2
        exit 1
    fi
}

check_no_build_inputs "${wheel##*/}" "$wheel_listing"
check_no_build_inputs "${sdist##*/}" "$sdist_listing"
check_package_manifest "${wheel##*/}" "$wheel_listing" ''
check_package_manifest "${sdist##*/}" "$sdist_listing" '[^/]+/src/'
check_package_manifest "working-tree ${tree_wheel##*/}" "$(unzip -Z1 "$tree_wheel")" ''
echo "wheels and sdist carry exactly the committed aco package"

UV_TOOL_DIR="$scratch/tools" UV_TOOL_BIN_DIR="$scratch/bin" \
    uv tool install --force "$wheel"
"$scratch/bin/aco" --help >/dev/null
echo "installed aco runs"

uv run --isolated --no-project --with "$wheel" python -c "
import sys
from importlib.resources import files
sys.exit(0 if files('aco.board').joinpath('static/index.html').is_file() else 1)
"
echo "importlib.resources finds aco/board/static/index.html"

# Proves the installed tool actually answers the shell over HTTP -- the
# importlib.resources check above only proves the file ships, not that
# `aco serve` can reach it.
serve_log="$scratch/serve.log"
XDG_STATE_HOME="$scratch/state" "$scratch/bin/aco" serve --port 0 --repo "$scratch" >"$serve_log" 2>&1 &
serve_pid=$!
for ((attempt = 0; attempt < 50; attempt++)); do
    [[ -s "$serve_log" ]] && break
    sleep 0.1
done
served_url="$(head -n1 "$serve_log")"
if [[ -z "$served_url" ]]; then
    echo "ERROR: aco serve printed no URL; log:" >&2
    cat "$serve_log" >&2
    exit 1
fi
uv run --isolated --no-project python -c "
import sys, urllib.request
url = '$served_url'.split('#', 1)[0]
with urllib.request.urlopen(url, timeout=5) as response:
    body = response.read()
    ok = response.status == 200 and response.headers.get('Content-Type', '').startswith('text/html')
    sys.exit(0 if ok and b'<div id=\"app\">' in body else 1)
"
kill "$serve_pid" 2>/dev/null || true
serve_pid=""
echo "aco serve answers / over HTTP"
