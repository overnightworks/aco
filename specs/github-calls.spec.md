# The GitHub call record

Every aco command that reaches GitHub through `gh` leaves one line per `gh` call in a file of
aco's state directory, so that the share of GitHub's rate limits that aco spends can be counted
across processes after the fact. It has no command of its own and changes no command's output.
`<state>` is aco's state directory, `$XDG_STATE_HOME/aco` when that is absolute, else
`~/.local/state/aco`. The free read of the rate limit that follows a refusal counts as a call.

## Behavior table

| state \ trigger | a `gh` call ends | a line cannot be written |
|---|---|---|
| `gh` started | CALLS-01, CALLS-02, CALLS-03, CALLS-04, CALLS-05 | CALLS-07 |
| `gh` could not be started | CALLS-01 | — |
| the record is past its size | CALLS-06 | CALLS-07 |
| any command | CALLS-08 | CALLS-08 |

- [ ] [CALLS-01] Every aco command appends one line to `<state>/github-calls.jsonl` for each `gh` call it starts, when that call ends, and never a second line for the same call (see E-CALLS-01).
  - A `gh` that could not be started adds none.
- [ ] [CALLS-02] A line is one JSON object with exactly the keys `at`, `command`, `repository`, `quota`, `outcome`, `pid`, `started`, in that order (see E-CALLS-01).
  - `at` and `started` are UTC, `YYYY-MM-DDTHH:MM:SSZ`; `at` is when the call ended, `started` when the command's recording began.
  - `command` is the aco command's name; `pid` the process id.
- [ ] [CALLS-03] `repository` is the `OWNER/REPO` the calling component works on, `null` for a search across owners and for a repository discovery.
- [ ] [CALLS-04] `outcome` is `not_modified` when GitHub answered 304, whatever `gh` exits; else `answered` when `gh` exited 0; else `rate_limited` when its output ends in a rate-limit refusal; else `failed`.
  - A call that gave no answer within its bounds is `failed`.
  - A repository discovery is judged on its exit status alone: `answered` or `failed`.
- [ ] [CALLS-05] `quota` is `graphql` for a GraphQL query or a repository discovery, `search` for a search page, `uncounted` for a read of the rate limit, and `core` for every other call.
- [ ] [CALLS-06] A line never holds a token, an argument, a path, a header value or a response body. The file is created readable by its owner alone, `0600`, and a state directory it has to create `0700`.
- [ ] [CALLS-07] A record past 32 MiB moves to `<state>/github-calls.1.jsonl`, replacing the one there, so that at most these two files exist.
- [ ] [CALLS-08] A line that cannot be written leaves the command unchanged and prints `warning: GitHub calls not recorded: <reason>` on stderr once; that process records no further line (see E-CALLS-02).
- [ ] [CALLS-09] No command's standard output, and no count it prints (`requests` in `aco board --json`), changes because of the record.

## Never

- The record never adds a GitHub request, and no command reads it.
- A write failure never fails or delays the command that made the call.

## Examples

### E-CALLS-01 -- one call, one line

Setup: `aco item show 7` makes one `gh` call, a REST read GitHub answered

```console
$ aco item show 7
```

`<state>/github-calls.jsonl` gains one line:

```json
{"at":"2026-11-22T20:01:09Z","command":"item","repository":"example/agent-coordination","quota":"core","outcome":"answered","pid":4242,"started":"2026-11-22T20:01:08Z"}
```

### E-CALLS-02 -- a record that cannot be written

Setup: `<state>` is a file, not a directory

```console
$ aco item show 7
2> warning: GitHub calls not recorded: Not a directory
{the command's own output}
exit 0
```

The warning appears once however many calls the command makes, and the command's output and exit status are those it has with a writable state directory.
