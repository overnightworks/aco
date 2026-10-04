#!/usr/bin/env bash
# Package smoke (issue #628): build the wheel and sdist with no Node on PATH and
# prove they carry the board's committed assets and install as working tools.
# CI's `package` job and release.yml both run it, so the release uploads only
# distributions this script has proven.
#
# Usage: scripts/package_smoke.sh [OUT_DIR]
#   OUT_DIR receives the built distributions (default: a temporary directory);
#   it must be empty or absent so every check reads the build it just made.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
out_dir="${1:-$scratch/dist}"

if [[ -n "$(ls -A "$out_dir" 2>/dev/null)" ]]; then
    echo "ERROR: $out_dir is not empty; the smoke must check only its own build" >&2
    exit 1
fi
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

# The committed assets are the manifest both archives must match exactly; a file
# that exists only in the working tree (a stray build output, a sourcemap) would
# otherwise ship unproven. Read before the narrowed PATH hides git.
expected_static="$scratch/expected-static"
git -C "$repository_root" ls-files -- src/aco_board/static \
    | sed 's|^src/aco_board/static/||' | sort >"$expected_static"

# A PATH holding only the tools this script needs proves the install path never
# reaches for Node, which a developer machine or CI runner usually has.
# UV_PYTHON pins the interpreter found now, before the narrowed PATH hides it.
UV_PYTHON="$(uv python find)"
export UV_PYTHON
tool_path="$scratch/path"
mkdir -p "$tool_path"
for tool in uv unzip tar gzip grep sed sort diff rm; do
    ln -s "$(command -v "$tool")" "$tool_path/$tool"
done
export PATH="$tool_path"
if command -v node >/dev/null; then
    echo "ERROR: node is still reachable on the narrowed PATH" >&2
    exit 1
fi

uv build --quiet --out-dir "$out_dir" "$repository_root"

# The release uploads every distribution in OUT_DIR, so it must hold exactly
# the one wheel and one sdist proven below.
shopt -s nullglob
distributions=("$out_dir"/*)
wheels=("$out_dir"/*.whl)
sdists=("$out_dir"/*.tar.gz)
shopt -u nullglob
if ((${#wheels[@]} != 1 || ${#sdists[@]} != 1 || ${#distributions[@]} != 2)); then
    echo "ERROR: $out_dir must hold exactly one wheel and one sdist, found:" >&2
    printf '  %s\n' "${distributions[@]##*/}" >&2
    exit 1
fi
wheel="${wheels[0]}"
sdist="${sdists[0]}"

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

# Compares an archive's static files, relative to aco_board/static/, with the
# committed manifest and names every missing or extra file.
check_static_manifest() {
    local archive="$1" listing="$2" static_prefix="$3" shipped
    shipped="$(grep -E "^${static_prefix}[^/]" <<<"$listing" | grep -v '/$' \
        | sed -E "s|^${static_prefix}||" | sort || true)"
    if ! diff -u --label committed --label "$archive" "$expected_static" - <<<"$shipped" >&2; then
        echo "ERROR: $archive static files differ from src/aco_board/static (see diff above)" >&2
        exit 1
    fi
}

check_no_build_inputs "${wheel##*/}" "$wheel_listing"
check_no_build_inputs "${sdist##*/}" "$sdist_listing"
check_static_manifest "${wheel##*/}" "$wheel_listing" 'aco_board/static/'
check_static_manifest "${sdist##*/}" "$sdist_listing" '[^/]+/src/aco_board/static/'
echo "wheel and sdist carry exactly the committed board assets"

UV_TOOL_DIR="$scratch/tools" UV_TOOL_BIN_DIR="$scratch/bin" \
    uv tool install --force "$wheel"
"$scratch/bin/aco" --help >/dev/null
"$scratch/bin/aco-board" --help >/dev/null
echo "installed aco and aco-board run"

uv run --isolated --no-project --with "$wheel" python -c "
import sys
from importlib.resources import files
sys.exit(0 if files('aco_board').joinpath('static/index.html').is_file() else 1)
"
echo "importlib.resources finds aco_board/static/index.html"
