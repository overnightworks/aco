Repository facts only; the global contract owns every general rule.

Entry points (pointers only; the facts live there): `README.md` is operator documentation for install, the CLI, and the claim protocol. Follow the installed `aco` CLI for the live rules. `specs/*.spec.md` owns every command's behaviour -- its printed literals, exit codes, and `--json` shapes.

Repository facts (owners in parentheses):
- Python >= 3.11 (`pyproject.toml`).
- Verification (`.github/workflows/ci.yml` lists the exact steps): `uv sync --locked --group dev`, then `uv run --locked` for `ruff check .`, `ruff format --check .`, `pyright src tests scripts`, `lint-imports`, and `pytest`; for `frontend/`, `pnpm --dir frontend install --frozen-lockfile`, then `check`, `lint`, `knip`, `test`, and `build`, and commit the rebuilt `src/aco_board/static/`.
- Quality gate: the `quality` job in `.github/workflows/ci.yml` calls overnightworks/quality's `gate.yml`; its required check is `quality / verdict`, and `quality/config.toml` lists the mandatory jobs. Sonar and secret scans run there, not in separate jobs.
- Package version: `src/agent_coordination/__init__.py` (`__version__`).
- Build in a linked isolated worktree. Use live `aco status` then `claim` before the first edit.
