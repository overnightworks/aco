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

# A PATH holding only the tools this script needs proves the install path never
# reaches for Node, which a developer machine or CI runner usually has.
# UV_PYTHON pins the interpreter found now, before the narrowed PATH hides it.
UV_PYTHON="$(uv python find)"
export UV_PYTHON
tool_path="$scratch/path"
mkdir -p "$tool_path"
for tool in uv unzip tar gzip grep rm; do
    ln -s "$(command -v "$tool")" "$tool_path/$tool"
done
export PATH="$tool_path"
if command -v node >/dev/null; then
    echo "ERROR: node is still reachable on the narrowed PATH" >&2
    exit 1
fi

uv build --quiet --out-dir "$out_dir" "$repository_root"
wheels=("$out_dir"/*.whl)
sdists=("$out_dir"/*.tar.gz)

# Listings are read whole before grep: `lister | grep -q` lets grep close the
# pipe early, and pipefail would report the lister's SIGPIPE as a missing file.
wheel_listing="$(unzip -l "${wheels[0]}")"
sdist_listing="$(tar tzf "${sdists[0]}")"
for asset in aco_board/static/index.html aco_board/static/assets/index.js; do
    grep -q "$asset" <<<"$wheel_listing" || {
        echo "ERROR: wheel lacks $asset" >&2
        exit 1
    }
    grep -q "src/$asset" <<<"$sdist_listing" || {
        echo "ERROR: sdist lacks src/$asset" >&2
        exit 1
    }
done
echo "wheel and sdist carry the board assets"

UV_TOOL_DIR="$scratch/tools" UV_TOOL_BIN_DIR="$scratch/bin" \
    uv tool install --force "${wheels[0]}"
"$scratch/bin/aco" --help >/dev/null
"$scratch/bin/aco-board" --help >/dev/null
echo "installed aco and aco-board run"

uv run --isolated --no-project --with "${wheels[0]}" python -c "
import sys
from importlib.resources import files
sys.exit(0 if files('aco_board').joinpath('static/index.html').is_file() else 1)
"
echo "importlib.resources finds aco_board/static/index.html"
