# `.aco/ahead-of-caller.toml`

The list of code built ahead of its caller: one entry per piece of code, naming the path, the item that will call it and the reason. An entry whose item is not open is red. This file owns the file's place and format, the sentences that refuse a malformed file, how the items are read and what red is; `specs/next.spec.md` owns what `aco next` prints and carries (NEXT-49..55). The file is read only from the trunk of the last fetch, never from the worktree. `<n>` is an item number or, in a refusal sentence, the entry's position counted from 1; `<sentence>` is one refusal sentence from the table below; `<list>` is `.aco/ahead-of-caller.toml`.

## Behavior table

| state \ trigger | reading | red |
|---|---|---|
| no file, an empty file, or no `code` | AHEAD-01 | — |
| the trunk cannot be resolved | AHEAD-15 | — |
| the trunk's file cannot be read | AHEAD-02 | — |
| the file is only in the worktree | AHEAD-03 | — |
| the file is malformed | AHEAD-04..AHEAD-09, AHEAD-16..AHEAD-19 | — |
| an entry names an item of this repository | AHEAD-10 | AHEAD-12 |
| an entry names an item of another repository | AHEAD-11 | AHEAD-12 |
| two entries name one item | AHEAD-13 | AHEAD-12 |
| the item's state is not open | — | AHEAD-12 |
| the forge fails on one item | AHEAD-14 | AHEAD-12 |

## The file

- [ ] [AHEAD-01] The file is `.aco/ahead-of-caller.toml`. A missing file, an empty file, or a file without `code` holds no entries.
- [ ] [AHEAD-02] A trunk file git cannot show, or whose bytes are no UTF-8, makes the list unavailable with `<list> cannot be read: <error>`, `<error>` the failure's text; a directory there is AHEAD-04's bad TOML.
- [ ] [AHEAD-15] A trunk that does not resolve refuses `aco next` whole as `unavailable` with git's text (`specs/next.spec.md`, Refusals), so the list is never read as no file.
- [ ] [AHEAD-03] Only the trunk's copy counts: a file that exists only in the worktree is ignored.
- [ ] [AHEAD-04] The top level holds only `code`, an array of tables. Bad TOML refuses `<list> is not valid TOML: <error>`, `<error>` the parser's text.
- [ ] [AHEAD-16] Another top-level key (`[[cod]]` too) refuses `<list> has the unknown top-level key '<key>'`, `<key>` the first in sorted order; a `code` that is no array of tables, `<list>: 'code' must be an array of tables`.
- [ ] [AHEAD-05] Each entry has exactly `path`, `item` and `reason`, all strings. In that order the first failing key refuses `<list>: code entry <n> lacks '<key>'` or `... has '<key>' that is not a string`.
- [ ] [AHEAD-17] Then an extra key refuses `<list>: code entry <n> has the unknown key '<key>'`, `<key>` the first in sorted order.
- [ ] [AHEAD-06] `path` is repository-relative with forward slashes. An empty path, a leading `/` or a backslash refuses `<list>: code entry <n> has a path that is not repository-relative with forward slashes`.
- [ ] [AHEAD-18] A `..` segment refuses `<list>: code entry <n> has a path that holds a '..' segment`. Whether the path exists is not checked.
- [ ] [AHEAD-07] `reason` is one non-empty line; an empty, blank or multi-line reason refuses `<list>: code entry <n> has a reason that is not one non-empty line`.
- [ ] [AHEAD-08] `item` is `aco-xxxxxx`, `#n` or `n` for this repository, or `<owner>/<repo>#<n>` for another; any other form refuses `<list>: code entry <n> has an item '<item>' that is not aco-xxxxxx, #n, n or OWNER/REPO#n`.
- [ ] [AHEAD-09] Two entries with the same `path` and the same item refuse `<list>: code entry <n> repeats the path and item of an earlier entry`, `<n>` the later one.
- [ ] [AHEAD-19] A malformed file is unavailable as a whole: the first sentence in file order is the one. Per entry the checks run keys, path, reason, item.

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

### E-AHEAD-02 — an entry that repeats an earlier one

Setup: the trunk holds two `[[code]]` tables with `path = "src/token.py"` and `item = "#12"`

```console
$ aco next --json
{"ok": true, ..., "ahead_of_caller": [], "ahead_of_caller_unavailable": ".aco/ahead-of-caller.toml: code entry 2 repeats the path and item of an earlier entry", ...}
exit 0
```
