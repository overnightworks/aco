# 0002 — Keep the item store and the board while they are unused

Status: accepted. Both features stay; nothing is removed.

Date: 06.11.2026.

Source: the operator's ruling of 06.11.2026 in aco's head session, after the read-only ballast audit at `cd8e99f3` (distributor issue overnightworks/aco#658, which holds the full evidence).

## 1. Context

The audit found two features with no current use: the item store has never had a user, and the board has decided nothing since 30.10.2026.

**The state-ref item store** (`storage = "state-ref"` in `.aco/board.toml`, README "No forge"). It keeps items as files in `refs/aco/state` for a repository without a forge, with `aco item new/show/edit/close` and a `Work-Item:` trailer on the trunk commit (`specs/storage-pin.spec.md`).

- None of the 15 overnightworks repositories that coordinate with aco sets `storage`, and none ever pinned `state-ref`. Session transcripts hold 0 calls of `aco item close` and of `aco item new --origin`.
- Size: about 1,900 production lines (`src/aco/state_board.py`, `src/aco/items.py`, the state-ref paths in `cmd_item`, `store`, `protocol` and `session`, and the `storage` parameter in about 25 modules), plus 8,000 to 9,000 test lines.

**The decision board** (`aco serve`, `src/aco/board/`, `frontend/`, `specs/serve.spec.md`, `docs/board/`). It is frozen by the operator's ruling on aco#648 (06.11.2026): nothing more is built at it.

- Usage: of 68 rulings since 27.10.2026, 16 came by board, the last on 30.10.2026; 51 came by chat and 1 by default.
- Size: 5,081 production lines (1,107 Python, 3,974 frontend), about 12,800 test lines, the `frontend` and `e2e` CI jobs and the npm Dependabot stream.
- His earlier word, quoted in aco#24 (21.10.2026): „Board nur mit Keycloak, nicht löschen, jetzt keine Priorität“.

## 2. Decision

Both stay. The operator may still take them into use; this record exists so that the question, if it comes back, starts from these numbers. His words (06.11.2026), where „ihn“ is the state-ref item store:

- „nein wir behalten ihn, und auch das board! das wird noch nichtgenutzt aber ggf überlege ich es mir ja noch! wir könne beides irgendwo vermerken, falls die entscheidung nochmal kommt!“
- „dann kann man naohcmla darüber nachdenken“

## 3. Consequences

- A repository without a forge, and deciding by page, stay possible without a rebuild.
- A later ballast audit names both as kept by this record and brings its numbers up to date, instead of raising them as new findings. Whether to look again is the operator's call.
- Keeping them costs the upkeep the numbers above show. Every change to `session`, `store` and the item commands still carries both storage paths.
- The board stays as aco#648 froze it.

## 4. Revisit

When the question comes up again, from the operator or from a later audit that points here. The numbers above are the starting point and are measured again then.
