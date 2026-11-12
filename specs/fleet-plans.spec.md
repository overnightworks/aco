# `aco fleet-plans`

`aco fleet-plans [--json]` lists, read-only, the open items of every repository on this machine that carry the label `fleet-plan`: a plan that binds repositories other than its own (a rename, a
publication order, a migration every repository joins). A head sets the label on the forge (`gh issue edit <n> --add-label fleet-plan`, under `storage = "state-ref"` through the item's record labels) and
removes it when the plan is done; aco never sets it. The command starts from any working directory, takes no `--repo`, finds its repositories as `aco mcp` does (`specs/serve.spec.md`, ABRD-14,
ABRD-108..ABRD-111) and reads each one's open items in parallel, as the inbox does. It keeps no cache and sets no deadline: a caller that must answer fast caps the run itself. Only items a member of the repository
wrote are listed, the boundary `specs/mcp.spec.md` draws for the inbox; under `storage = "state-ref"` every item counts as a member's. Every listed plan answers every action: a plan names no kinds of action.
`specs/output.spec.md` owns the `--json` envelope (OUT-nn).

## Behavior table

| state \ trigger | text | `--json` |
|---|---|---|
| an open, labelled, member-written item in a readable repository | FLP-01, FLP-03 | FLP-01, FLP-04 |
| an unlabelled, closed or non-member item | FLP-02 | FLP-02 |
| several plans | FLP-05 | FLP-05 |
| no plan in any readable repository | FLP-06 | FLP-06 |
| one repository cannot be read, others can | FLP-07 | FLP-07 |
| no repository can be read, or no root is configured | FLP-08 | FLP-08 |
| the global `--repo` | FLP-09 | FLP-09 |
| a title or reason holds a display control | FLP-10 | FLP-10 |

## Listing

- [ ] [FLP-01] An open, member-written item labelled `fleet-plan` is listed from any repository's checkout, that repository's own and every other's alike (see E-FLP-01).
- [ ] [FLP-02] An item without the label, a closed item and an item a non-member wrote are never listed (see E-FLP-01).
- [ ] [FLP-03] Text prints one line per plan, `<repository>#<n> <day>: <title> <url>`; `<day>` is the last-changed day, `<url>` left out when there is none (see E-FLP-01).
- [ ] [FLP-05] Plans are ordered by repository `OWNER/REPO`, then by ascending `<n>` (see E-FLP-02).
- [ ] [FLP-06] With no plan, text is exactly `No fleet-wide plans.`, exit `0`; `--json` has `"plans": []` (see E-FLP-03).
- [ ] [FLP-10] Text shows `<title>` and an unavailable `<reason>` with each display control escaped (NEXT-37); `--json` carries both as stored.

## `--json`

- [ ] [FLP-04] A plan is `{"repository", "number", "title", "url", "updated_on"}`; `url` is the item's forge page, `null` under `storage = "state-ref"`; `updated_on` is `YYYY-MM-DD` (see E-FLP-01).
- [ ] [FLP-11] Success is `{"ok": true, "reason": "listed", "plans", "unavailable"}`, exit `0`; an `unavailable` entry is `{"repository", "reason"}`, in discovery order, the repositories first and the unreadable checkouts after them (see E-FLP-04).

## Unavailable repositories and refusals

- [ ] [FLP-07] An unreadable repository, or a checkout discovery cannot read (named by its directory), prints `unavailable <repository>: <reason>` after the plans, and is under `unavailable` in `--json`; the others answer, exit `0` (see E-FLP-04).
- [ ] [FLP-08] With no readable repository or no usable root: `ERROR: <sentence>` on stderr, exit `2`; `--json` has `reason` `unavailable` (see E-FLP-05).
- [ ] [FLP-09] The global `--repo` refuses `aco fleet-plans finds its repositories itself; --repo does not apply to it`, exit `2`; `--json` has `reason` `invalid_usage` (see E-FLP-06).

`reason`, by which refusal fired:

| refusal | `reason` |
|---|---|
| FLP-09 (`--repo`) | `invalid_usage` |
| FLP-08 (no root, no readable repository) | `unavailable` |

## Never

- `aco fleet-plans` never changes an item, a label or a claim, and never sets the label itself.
- It reads each repository's open-item listing and nothing else: no claim, pull request or dependency read.

## Examples

`Setup: fleet` is a configured root holding two checkouts, `acme/here` and `acme/there`, each tracking `.aco/board.toml`, with a fake forge. `#2` of `acme/there` is open, labelled `fleet-plan`, written by a member, titled `Rename every repository`, last changed on 2026-11-12. `#3` of `acme/there` is open and unlabelled, `#4` is labelled and closed, `#5` is labelled and written by a stranger.

### E-FLP-01 — one plan, from the other repository's checkout

Setup: fleet, the command run in `acme/here`

```console
$ aco fleet-plans
acme/there#2 2026-11-12: Rename every repository https://github.com/acme/there/issues/2
exit 0
$ aco fleet-plans --json
{"ok": true, "reason": "listed", "plans": [{"repository": "acme/there", "number": 2, "title": "Rename every repository", "url": "https://github.com/acme/there/issues/2", "updated_on": "2026-11-12"}], "unavailable": []}
exit 0
```

### E-FLP-02 — the order

Setup: fleet, `#9` and `#3` of `acme/here` labelled and open, as `#2` of `acme/there`

```console
$ aco fleet-plans
acme/here#3 2026-11-12: Publication order https://github.com/acme/here/issues/3
acme/here#9 2026-11-12: Archive the old names https://github.com/acme/here/issues/9
acme/there#2 2026-11-12: Rename every repository https://github.com/acme/there/issues/2
exit 0
```

### E-FLP-03 — no plan

Setup: fleet, no item labelled `fleet-plan`

```console
$ aco fleet-plans
No fleet-wide plans.
exit 0
$ aco fleet-plans --json
{"ok": true, "reason": "listed", "plans": [], "unavailable": []}
exit 0
```

### E-FLP-04 — a repository the forge cannot be asked about

Setup: fleet, the forge answers `rate limited` for `acme/here`

```console
$ aco fleet-plans
acme/there#2 2026-11-12: Rename every repository https://github.com/acme/there/issues/2
unavailable acme/here: rate limited
exit 0
$ aco fleet-plans --json
{"ok": true, "reason": "listed", "plans": [{"repository": "acme/there", "number": 2, "title": "Rename every repository", "url": "https://github.com/acme/there/issues/2", "updated_on": "2026-11-12"}], "unavailable": [{"repository": "acme/here", "reason": "rate limited"}]}
exit 0
```

### E-FLP-05 — nothing can be read

Setup: fleet, the forge answers `rate limited` for both repositories

```console
$ aco fleet-plans
2> ERROR: no repository could be read under /home/me/git (acme/here: rate limited; acme/there: rate limited)
exit 2
$ aco fleet-plans --json
2> ERROR: no repository could be read under /home/me/git (acme/here: rate limited; acme/there: rate limited)
{"ok": false, "reason": "unavailable", "message": "no repository could be read under /home/me/git (acme/here: rate limited; acme/there: rate limited)"}
exit 2
```

With no config file, the sentence is `ERROR: <config path> does not exist; create it with root = "<absolute path>"`, the same `reason`, exit `2`.

### E-FLP-06 — `--repo`

Setup: fleet

```console
$ aco --repo acme/there fleet-plans --json
2> ERROR: aco fleet-plans finds its repositories itself; --repo does not apply to it
{"ok": false, "reason": "invalid_usage", "message": "aco fleet-plans finds its repositories itself; --repo does not apply to it"}
exit 2
```
