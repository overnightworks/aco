# aco

## Commands

- `uv sync --locked --group dev`: install the Python dependencies; run it before any Python command below.
- `PYTEST_XDIST_AUTO_NUM_WORKERS=4 uv run --locked pytest -n 4 <test paths or -k selection>`: run selected Python tests.
- `uv lock --check`, `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked pyright src tests scripts`, `uv run --locked vulture src scripts/vulture_whitelist.py --min-confidence 60`: the static checks of CI's `check` job.
- `pnpm --dir frontend install --frozen-lockfile`: install the frontend dependencies.
- `pnpm --dir frontend test <test paths>`: run selected frontend tests.
- `pnpm --dir frontend build`: build the board into `src/aco/board/static/`; run the install first.
- `uv run --locked --project <quality checkout at the commit .github/workflows/ci.yml pins> quality check`: run the gate's rules locally; add `--fix` to rewrite `quality/baseline.toml`.

## Rules

- A change under `frontend/` commits the rebuilt `src/aco/board/static/` in the same change; CI's step "Assets fresh" fails on any difference.
- `quality/baseline.toml` is written only by `quality check --fix` from the pinned quality checkout, never by hand or by the installed `quality` CLI.
- In a worktree that uses the main checkout's shared virtualenv, run Python tests with `PYTHONPATH=src` from the worktree root: its editable install points at the main checkout.

## Owners

- overnightworks/marketplace owns the contract and the atelier skills and workflows that drive aco, the `aco` skill among them.
- overnightworks/quality owns the gate and its rules.
- A change wished for in either goes to that repository's board, not into aco.

## Documents

- `README.md`: read to install aco and run one lane.
- `docs/VISION.md`: read when judging whether a change fits what aco is for.
- `docs/ARCHITECTURE.md`: read when a change moves a part, a boundary or a dependency direction.
- `specs/`: read when changing what a command does, prints, refuses or returns; each file is named by its command or contract.
