# `.aco/ahead-of-caller.toml`

The list of code built ahead of its caller: one entry per piece of code, naming the path, the item that will call it and the reason. An entry whose item is not open is red. This file owns the file's place and format, the sentences that refuse a malformed file, how the items are read and what red is; `specs/next.spec.md` owns what `aco next` prints and carries (NEXT-49..55). The file is read only from the trunk of the last fetch, never from the worktree. `<n>` is an item number, `<sentence>` one refusal sentence.

## Behavior table

| state \ trigger | reading | red |
|---|---|---|
| no file, an empty file, or no `code` | AHEAD-01 | — |
| the trunk cannot be resolved, or the path is no readable file | AHEAD-02 | — |
| the file is only in the worktree | AHEAD-03 | — |
| the file is malformed | AHEAD-04..AHEAD-09 | — |
| an entry names an item of this repository | AHEAD-10 | AHEAD-12 |
| an entry names an item of another repository | AHEAD-11 | AHEAD-12 |
| two entries name one item | AHEAD-13 | AHEAD-12 |
| the item's state is not open | — | AHEAD-12 |
| the forge fails on one item | AHEAD-14 | AHEAD-12 |

## The file

- [ ] [AHEAD-01] The file is `.aco/ahead-of-caller.toml`. A missing file, an empty file, or a file without `code` holds no entries.
- [ ] [AHEAD-02] A trunk that does not resolve, or a trunk path that is no readable file, makes the list unavailable with a sentence; it is never read as no file.
- [ ] [AHEAD-03] Only the trunk's copy counts: a file that exists only in the worktree is ignored.
- [ ] [AHEAD-04] The top level holds only `code`, an array of tables. Bad TOML, any other top-level key (`[[cod]]` too) or a `code` that is not an array of tables is malformed.
- [ ] [AHEAD-05] Each entry has exactly `path`, `item` and `reason`, all strings; a missing key, an extra key or a value that is no string is malformed.
- [ ] [AHEAD-06] `path` is repository-relative with forward slashes: an empty path, a leading `/`, a backslash or a `..` segment is malformed. Whether the path exists is not checked.
- [ ] [AHEAD-07] `reason` is one non-empty line; an empty, blank or multi-line reason is malformed.
- [ ] [AHEAD-08] `item` is `aco-xxxxxx`, `#n` or `n` for this repository, or `<owner>/<repo>#<n>` for another; any other form is malformed.
- [ ] [AHEAD-09] Two entries with the same `path` and the same item are malformed. A malformed file is unavailable as a whole, and one sentence names the field and the entry.

## Reading items

- [ ] [AHEAD-10] An item of this repository is read through this repository's own board, under both storages.
- [ ] [AHEAD-11] `<owner>/<repo>#<n>` is always that repository's GitHub issue.
- [ ] [AHEAD-13] Each distinct item is read once, however many entries name it.
- [ ] [AHEAD-14] A forge failure on one item makes only that entry `unreadable` with the failure's text; the other entries are judged.

## Red

- [ ] [AHEAD-12] An entry is red unless its item is open: closed, missing (`not found or not accessible`), a pull request or unreadable. The released `aco` that does not read the file is unaffected.

## Never

- The list never blocks `aco land`, `aco check` or `aco status`; red only shows in `aco next`.
- The reading never writes anything.

## Examples

### E-AHEAD-01 — a list with a bad key

Setup: the trunk holds `.aco/ahead-of-caller.toml` with a `[[cod]]` table

```console
$ aco next
...
ahead of caller: unavailable (.aco/ahead-of-caller.toml has the unknown top-level key 'cod')
exit 3
```
