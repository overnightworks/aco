# Body block

The `aco` fenced TOML block inside a work item's body: the one grammar
`aco board`, `aco next`, issue-mode `aco claim`, `aco cut`, `aco rulings` and
`aco check` read a work item from. This file owns the block's shape, its
defect sentences, and the two verdicts a body can carry (`malformed`,
`incomplete`). The commands appear here only as far as they make the contract
visible; each command's own spec owns its flags and its other output and cites
these IDs instead of restating them.

Every defect sentence below is printed by `aco check -` on stderr, one
line per defect, and by a reader as the item's own reason (BODY-50..BODY-52).
`<n>` is an item number, `<path>` a repository-relative path, `<keys>` the
empty projection keys, comma-joined in the order `Now, Next, Done when`.

## Behavior table

| body state \ trigger | `aco check -` | `aco board` | `aco claim <n>` |
|---|---|---|---|
| no `aco` fence | BODY-01 | BODY-50 | BODY-52 |
| fence opened, never closed | BODY-02 | BODY-50 | BODY-52 |
| two `aco` fences | BODY-03 | BODY-50 | BODY-52 |
| fence content is not TOML | BODY-04 | BODY-50 | BODY-52 |
| block quoted inside a documentation fence | BODY-05 | BODY-50 | BODY-52 |
| valid block, prose around it | BODY-06, BODY-07 | — | — |
| `version` missing or not `1` | BODY-08, BODY-09 | BODY-50 | BODY-52 |
| `now`/`next`/`done_when` missing or not a string | BODY-10, BODY-11 | BODY-50 | BODY-52 |
| every projection key present, one or more empty | BODY-12 | BODY-51 | BODY-52 |
| unknown top-level key | BODY-13 | BODY-50 | BODY-52 |
| `[record]` under `storage = "github"` | BODY-15 | BODY-50 | BODY-52 |
| `[record]` under `storage = "state-ref"` | BODY-16..BODY-20 | — | — |
| `frozen_until` defective | BODY-21..BODY-24 | BODY-50 | BODY-52 |
| `[[expectation]]` defective | BODY-25..BODY-33 | BODY-50 | BODY-52 |
| card field defective | BODY-34, BODY-36..BODY-42 | BODY-50 | BODY-52 |
| `question` of exactly 160 characters | BODY-35 | — | — |
| option line defective | BODY-69..BODY-84, BODY-86, BODY-87, BODY-90 | BODY-50 | BODY-52 |
| complete option line, open or ruled | BODY-85, BODY-89 | — | — |
| a rewrite of a block carrying expectation lines | BODY-88 | — | — |
| `[[slice]]` defective | BODY-43..BODY-48, BODY-65 | BODY-50 | BODY-52 |
| a `[[slice]]` title holding a display control (`specs/next.spec.md`) | BODY-63 | BODY-64 | BODY-64 |
| a `[[slice]]` `done_when` holding a display control | BODY-66 | BODY-64 | BODY-64 |
| `slice = []` | BODY-49, BODY-67 | — | — |
| a key or message of any defect holding a display control | BODY-68 | BODY-68 | BODY-68 |
| `scope` defective | BODY-53..BODY-56 | BODY-50 | BODY-52 |
| `size` valid or defective | BODY-57..BODY-59 | BODY-50 (defective only) | BODY-52 (defective only) |
| `whole` valid or defective | BODY-60..BODY-62 | BODY-50 (defective only) | BODY-52 (defective only) |
| complete valid block | BODY-14 | — | — |

## Fence and surroundings

- [ ] [BODY-01] A body with no `aco` fence makes `aco check -` print `body malformed: aco: no aco block` on stderr, exit `2` — never a sentence about another grammar.
- [ ] [BODY-02] A body whose `aco` fence is opened and never closed makes `aco check -` print `body malformed: aco: unclosed aco block` on stderr, exit `2`.
- [ ] [BODY-03] A body with two `aco` fences makes `aco check -` print `body malformed: aco: multiple aco blocks; exactly one is allowed` on stderr, exit `2`.
- [ ] [BODY-04] A fence whose content is not TOML makes `aco check -` print `body malformed: aco: aco block is not valid TOML: <reason>` on stderr, exit `2`.
- [ ] [BODY-05] An `aco` fence quoted inside a longer documentation fence is not the item's block, so a body carrying only that one prints `body malformed: aco: no aco block`, exit `2`.
- [ ] [BODY-06] Prose beside the block — headings, a `Blocked by: nichts` line, another tool's own section — carries no contract, so a body of prose plus one complete block prints `body ok`, exit `0`.
- [ ] [BODY-07] A block whose lines end in CRLF is read like any other: a complete CRLF body prints `body ok`, exit `0`; a rewrite keeps CRLF but re-renders the block's fields canonically, not byte-for-byte.

## Projection keys

- [ ] [BODY-08] A block without `version` prints `body malformed: version: version is required and must be 1` on stderr, exit `2`.
- [ ] [BODY-09] A block whose `version` is any value but the integer `1` prints `body malformed: version: version must be exactly 1` on stderr, exit `2`.
- [ ] [BODY-10] A block missing `now`, `next` or `done_when` prints one `body malformed: <key>: <key> is required` line per missing key on stderr, exit `2`.
- [ ] [BODY-11] A block whose `now`, `next` or `done_when` is not a string prints `body malformed: <key>: <key> must be a string` on stderr, exit `2`.
- [ ] [BODY-12] A block whose projection keys are present but not all filled is valid but unfilled: `aco check -` prints `body incomplete: <keys>` on stderr, exit `2` (see E-BODY-02).
- [ ] [BODY-13] A top-level key outside `version`, `now`, `next`, `done_when`, `frozen_until`, `scope`, `size`, `whole`, `expectation`, `slice` prints `body malformed: <key>: unknown top-level key <key>`, exit `2`.
- [ ] [BODY-14] A block whose three projection keys are all non-empty and whose optional tables are valid prints `body ok` on stdout, exit `0`, with nothing on stderr (see E-BODY-01).

## `[record]`, the state-ref item identity

- [ ] [BODY-15] Under `storage = "github"` a `[record]` table is an unknown key: `aco check -` prints `body malformed: record: unknown top-level key record` on stderr, exit `2`.
- [ ] [BODY-16] Under `storage = "state-ref"` a `[record]` carrying `title`, `state`, `created_at`, `updated_at` is valid: `aco check -` prints `body ok`, exit `0` (see E-BODY-05).
- [ ] [BODY-17] A `[record]` whose `state` is neither `open` nor `closed` prints `body malformed: record.state: record.state must be open or closed` on stderr, exit `2`.
- [ ] [BODY-18] A `[record]` with `state = "closed"` and no `closed_at` prints `body malformed: record.closed_at: record.closed_at is required when record.state is closed`, exit `2`.
- [ ] [BODY-19] A `[record]` timestamp that is not an RFC 3339 UTC instant prints `body malformed: record.created_at: record.created_at must be an RFC 3339 UTC timestamp`, exit `2`.
- [ ] [BODY-20] A `[record]` key outside the ten allowed keys prints `body malformed: record.<key>: unknown key record.<key>`, exit `2`.

## `frozen_until`

- [ ] [BODY-21] A `frozen_until` that is not a table prints `body malformed: frozen_until.trigger: frozen_until must be a table with trigger and ruled_on` on stderr, exit `2`.
- [ ] [BODY-22] A `frozen_until` whose `trigger` is missing, blank or not a string prints `body malformed: frozen_until.trigger: frozen_until.trigger must be a non-empty string`, exit `2`.
- [ ] [BODY-23] A `frozen_until` whose `ruled_on` is not a TOML local date prints `body malformed: frozen_until.ruled_on: frozen_until.ruled_on must be a TOML local date`, exit `2`.
- [ ] [BODY-24] A `frozen_until` key outside `trigger` and `ruled_on` prints `body malformed: frozen_until.<key>: unknown key frozen_until.<key>` on stderr, exit `2`.

## `[[expectation]]`

- [ ] [BODY-25] An `expectation` key that is not an array of tables prints `body malformed: expectation: expectation must be an array of tables` on stderr, exit `2`.
- [ ] [BODY-26] An `[[expectation]]` entry that is not a table prints `body malformed: expectation[0]: expectation[0] must be a table` on stderr, exit `2`.
- [ ] [BODY-27] An entry whose `text` is missing, blank or not a string prints `body malformed: expectation[0].text: expectation[0].text must be a non-empty string`, exit `2`.
- [ ] [BODY-28] A yes/no entry carrying both `default` and a ruling prints `body malformed: expectation[0].default: expectation[0] must be proposed (default) or ruled (ruling, ruled_on), not both`, exit `2`.
- [ ] [BODY-29] A yes/no entry carrying neither prints `body malformed: expectation[0].default: expectation[0] must carry default, or both ruling and ruled_on`, exit `2`.
- [ ] [BODY-30] A yes/no entry whose `default` is not `yes`, `no` or `later` prints `body malformed: expectation[0].default: expectation[0].default must be yes, no, or later`, exit `2`.
- [ ] [BODY-31] A yes/no entry whose `ruling` is not `yes`, `no` or `later` prints `body malformed: expectation[0].ruling: expectation[0].ruling must be yes, no, or later`, exit `2`.
- [ ] [BODY-32] A ruled entry whose `ruled_on` is not a TOML local date prints `body malformed: expectation[0].ruled_on: expectation[0].ruled_on must be a TOML local date`, exit `2`.
- [ ] [BODY-33] An entry key its form does not know (a yes/no line: the seven keys above) prints `body malformed: expectation[0].<key>: unknown key expectation[0].<key>`, exit `2`; BODY-79/83/84 come first.

## The card fields `question`, `example`, `picture`

- [ ] [BODY-34] A `question` longer than 160 characters prints `body malformed: expectation[0].question: expectation[0].question must be at most 160 characters` on stderr, exit `2`.
- [ ] [BODY-35] A `question` of exactly 160 characters is inside the bound: `aco check -` prints `body ok` on stdout, exit `0`.
- [ ] [BODY-36] An `example` that is blank or not a string prints `body malformed: expectation[0].example: expectation[0].example must be a non-empty string` on stderr, exit `2`.
- [ ] [BODY-37] A `picture` whose text does not start with `<svg` prints `body malformed: expectation[0].picture: expectation[0].picture must be inline SVG rooted at <svg>`, exit `2`.
- [ ] [BODY-38] A `picture` over 8192 bytes prints `body malformed: expectation[0].picture: expectation[0].picture must be at most 8192 bytes` on stderr, exit `2`.
- [ ] [BODY-39] A `picture` containing `<script` in any casing prints `body malformed: expectation[0].picture: expectation[0].picture must not contain <script>`, exit `2`.
- [ ] [BODY-40] A `picture` carrying an event-handler attribute prints `body malformed: expectation[0].picture: expectation[0].picture must not contain an event-handler attribute`, exit `2`.
- [ ] [BODY-41] A `picture` whose `href` or `xlink:href` does not start with `#` prints `body malformed: expectation[0].picture: expectation[0].picture must not reference an href outside the document`, exit `2`.
- [ ] [BODY-42] A `picture` matching two refused contents names the earlier one in the order `<script>, <foreignObject>, on…=, javascript:, data:, href, animated href, url(), <iframe>, <embed>, <object>, srcdoc`.

## Option lines

An entry carrying `option` is an option line; any other is a yes/no line,
judged by BODY-26..BODY-42 exactly as before. Its keys, in the order a rewrite
writes them:

- `text`, then the decided state `ruling`, `ruled_on`, `card_hash`, `via` (all four, or none while open);
- `question`, `problem`, `picture` (TODAY), `caption`, `decision_kind`, `area`, `topic`, `recommended`, `reason`, each required;
- 2 to 4 `[[expectation.option]]` tables, each `name`, `effect`, then either `picture` with an optional `caption` or `same_as_today = true`, then `notice`, `cost`, `undo`, `undo_how`, `contract`.

The options' letters are `A`..`D` by position and never stored; `<L>` below
is the present letters, for example `A, B`. Inside one entry the refusals print
in this order: `text`, decided state, line keys, options, pictures, picture
budget, unknown keys, and last BODY-87, only when no other refusal fired.

- [ ] [BODY-69] An `option` that is not an array of tables prints `body malformed: expectation[0].option: expectation[0].option must be an array of tables`, exit `2` (see E-BODY-11).
- [ ] [BODY-70] Fewer than 2 or more than 4 options print `body malformed: expectation[0].option: expectation[0] must carry 2 to 4 options`, exit `2` (see E-BODY-11).
- [ ] [BODY-71] An option that is not a table prints `body malformed: expectation[0].option[1]: expectation[0].option[1] must be a table`, exit `2` (see E-BODY-11).
- [ ] [BODY-72] A missing line key, `picture` included, prints `body malformed: expectation[0].<key>: expectation[0].<key> is required`, exit `2` (see E-BODY-11).
- [ ] [BODY-73] An option missing a key prints `body malformed: expectation[0].option[1].<key>: expectation[0].option[1].<key> is required`, exit `2` (see E-BODY-11).
- [ ] [BODY-74] A blank or non-string text key of the line or an option prints `body malformed: <field>: <field> must be a non-empty string`, exit `2`; a long `question` stays BODY-34 (see E-BODY-11).
- [ ] [BODY-75] Another `decision_kind` prints `body malformed: expectation[0].decision_kind: expectation[0].decision_kind must be product, technical, data_risk, money, access, wording, or release` (see E-BODY-11).
- [ ] [BODY-76] An `undo` other than `reversible` or `final` prints `body malformed: expectation[0].option[0].undo: expectation[0].option[0].undo must be reversible or final` (see E-BODY-11).
- [ ] [BODY-77] A `recommended` that is not a present letter prints `body malformed: expectation[0].recommended: expectation[0].recommended must be one of <L>`, exit `2` (see E-BODY-11).
- [ ] [BODY-78] A `ruling` that is not a present letter prints `body malformed: expectation[0].ruling: expectation[0].ruling must be one of <L>`, exit `2`; a bad `ruled_on` keeps BODY-32 (see E-BODY-12).
- [ ] [BODY-79] A `default` or `example` on an option line prints `body malformed: expectation[0].<key>: expectation[0].<key> does not belong on an option line`, exit `2` (see E-BODY-11).
- [ ] [BODY-80] An option's result breaking one rule prints that rule's sentence below, exit `2` (see E-BODY-11):
  - neither `picture` nor `same_as_today`: `body malformed: expectation[0].option[1].picture: expectation[0].option[1] must carry exactly one of picture and same_as_today = true`
  - both: the same sentence under `expectation[0].option[1].same_as_today`
  - `same_as_today` not `true`: `body malformed: expectation[0].option[1].same_as_today: expectation[0].option[1].same_as_today must be true`
  - a `caption` without a picture: `body malformed: expectation[0].option[1].caption: expectation[0].option[1].caption needs a picture beside it`
- [ ] [BODY-81] Every picture, TODAY's and each option's, keeps BODY-37..BODY-42 under its own path, as `expectation[0].option[0].picture must not contain <script>` (see E-BODY-11).
- [ ] [BODY-82] All of a line's pictures over 16384 UTF-8 bytes together print `body malformed: expectation[0]: expectation[0] pictures must total at most 16384 bytes`, exit `2` (see E-BODY-11).
- [ ] [BODY-83] An option-line key (`problem` to `reason`) on a yes/no line prints `body malformed: expectation[0].<key>: expectation[0].<key> belongs to an option line; this line has none` (see E-BODY-11).
- [ ] [BODY-84] An option key it does not know, `letter` included, prints `body malformed: expectation[0].option[0].<key>: unknown key expectation[0].option[0].<key>`, exit `2` (see E-BODY-11).
- [ ] [BODY-85] A complete option line, open or ruled with its card's hash, prints `body ok` on stdout, exit `0` (see E-BODY-10).
- [ ] [BODY-86] A partial decided state prints exactly one sentence, by which keys it carries, exit `2`; a ruled line's `card_hash` must be `sha256:` and 64 lowercase hex digits (see E-BODY-12):
  - `ruling` without `ruled_on`: `body malformed: expectation[0].ruled_on: expectation[0] carries ruling without ruled_on`
  - `ruling` and `ruled_on`: `body malformed: expectation[0].card_hash: expectation[0] is ruled without card_hash`
  - `ruled_on`, no `ruling`: `body malformed: expectation[0].ruling: expectation[0] carries ruled_on without ruling`
  - `card_hash` alone: `body malformed: expectation[0].ruling: expectation[0] carries card_hash without ruling`
  - another `card_hash`: `body malformed: expectation[0].card_hash: expectation[0].card_hash must be sha256: followed by 64 lowercase hex digits`
  - `ruling`, `ruled_on` and `card_hash`: `body malformed: expectation[0].via: expectation[0] is ruled without via`
  - `via` alone: `body malformed: expectation[0].ruling: expectation[0] carries via without ruling`
- [ ] [BODY-87] A ruled card edited later prints `body malformed: expectation[0].card_hash: expectation[0] was edited after its ruling; a changed ruling is a new line` until reverted (see E-BODY-13).
- [ ] [BODY-88] A rewrite writes each present key in the order above, line keys before option tables; it re-reads to the same values, and a second rewrite changes no byte, LF or CRLF.
- [ ] [BODY-89] `card_hash` is `sha256:` and the SHA-256 hex of the shown card's present keys as compact, key-sorted UTF-8 JSON, the option tables under `options` (see E-BODY-10).
- [ ] [BODY-90] A `via` other than `board`, `chat` or `default` prints `body malformed: expectation[0].via: expectation[0].via must be board, chat, or default`, exit `2` (see E-BODY-12).

The card hash belongs to option lines and covers every key listed above except
the decided state. It never covers the item title, the index, `ruling`, `ruled_on`,
`card_hash` or `via`, and it reads parsed values, so TOML quoting, key order and line
endings cannot change it.

## `[[slice]]`

- [ ] [BODY-43] A `slice` key that is not an array of tables prints `body malformed: slice: slice must be an array of tables` on stderr, exit `2`.
- [ ] [BODY-44] A `[[slice]]` entry that is not a table prints `body malformed: slice[0]: slice[0] must be a table` on stderr, exit `2`.
- [ ] [BODY-45] An entry whose `index` is missing, zero, negative or not an integer prints `body malformed: slice[0].index: slice[0].index must be a positive integer`, exit `2`.
- [ ] [BODY-46] A second entry repeating an earlier `index` prints `body malformed: slice[1].index: slice[1].index duplicates slice index 4` on stderr, exit `2`.
- [ ] [BODY-47] An entry whose `title` is missing, blank or not a string prints `body malformed: slice[0].title: slice[0].title must be a non-empty string`, exit `2`; one line only (BODY-63).
- [ ] [BODY-63] A title holding a display control (NEXT-37) prints `body malformed: slice[0].title: slice[0].title of row <i> holds U+000B; a slice title stays on one line`, exit `2` (see E-BODY-06).
- [ ] [BODY-64] BODY-63 applies wherever a body's shape is judged — `aco check -`, `aco check <n>`, `aco item new`, `aco item edit`; `board`/`next` keep reading a stored body, `next` naming its row (NEXT-32).
- [ ] [BODY-48] An entry key outside `index`, `title`, `done_when` and `scope` prints `body malformed: slice[0].<key>: unknown key slice[0].<key>`, exit `2`; per-slice dependencies stay in the prose.
- [ ] [BODY-65] An entry may carry `done_when`, its child's done-when (CUT-25); a blank or non-string one prints `body malformed: slice[0].done_when: slice[0].done_when must be a non-empty string` (E-BODY-07).
- [ ] [BODY-66] A row `done_when` holding a display control prints `body malformed: slice[0].done_when: slice[0].done_when of row <i> holds U+000B; a slice done_when stays on one line`, exit `2`, as BODY-64.
- [ ] [BODY-49] A block carrying `slice = []` is valid with nothing left to cut: `aco check -` prints `body ok`, exit `0`, and the empty table stays present in the body.
- [ ] [BODY-67] A rewrite keeps `slice = []` among the top-level keys, ahead of the first `[[expectation]]` table, so a body whose last row was cut still prints `body ok` (see E-BODY-08).

## What a reader does with a defect

- [ ] [BODY-50] An item whose body carries any defect above is named by `aco board` with its first defect sentence as its reason, `body malformed: <field>: <message>`, and is never proposed as a cut or a close.
- [ ] [BODY-51] An item whose block is valid but carries an empty projection key is skipped by `aco next`, which names it `SKIPPED` with BODY-12's `body incomplete: <keys>`.
- [ ] [BODY-52] Issue-mode `aco claim <n>` against such an item refuses before any write with the same sentence as a `body-contract` check, exit `2` (see E-BODY-03); under `state-ref` PIN-15 refuses, `unavailable`.
- [ ] [BODY-68] Every sentence and `--json` field naming a malformed body's defect shows each display control as NEXT-37 does; all other text is byte for byte the same (see E-BODY-09).

## `scope`, the item's own files

- [ ] [BODY-53] A block carrying `scope = ["README.md", "docs"]` is valid, and a `[[slice]]` row may carry its own `scope = ["docs"]` under the same grammar: `aco check -` prints `body ok`, exit `0`.
- [ ] [BODY-54] `scope = []` prints `body malformed: scope: scope must name at least one path`, exit `2`; an empty `[[slice]]` row `scope` prints the `slice[0].scope` form. Absent `scope` means unknown, never empty.
- [ ] [BODY-55] A `scope = ["/etc/passwd"]` entry fails the same way `claim --scope` would: `body malformed: scope: claim scope must be repository-relative: '/etc/passwd'`.
- [ ] [BODY-56] A valid `scope` renders sorted, deduplicated, ahead of the first `[[expectation]]`/`[[slice]]` table — else TOML binds a bare key to the prior table — so a re-read names the same canonical `scope`.

## `size`, the item's own estimate class

- [ ] [BODY-57] A block with no `size` key is valid: absence means "no estimate", never a default class, and `aco check -` prints `body ok`, exit `0`.
- [ ] [BODY-58] `size = "S"`, `"M"`, or `"L"` is valid: `aco check -` prints `body ok`, exit `0`.
- [ ] [BODY-59] A `size` outside `S`/`M`/`L` prints `body malformed: size: size must be S, M, or L`, exit `2`, the same sentence for every invalid shape.

  ```
  size = "XL"    # not one of S, M, L
  size = ["S"]   # a list, not a scalar
  size = {}      # a table, not a scalar
  ```

## `whole`, the item's own wide-scope justification

- [ ] [BODY-60] A block with no `whole` key is valid: absence means no stored reason, never a default one, and `aco check -` prints `body ok`, exit `0`.
- [ ] [BODY-61] `whole = "<reason>"` is valid for one non-empty line of at most 512 characters, unpadded, with no control character or display control (NEXT-37): `aco check -` prints `body ok`, exit `0`.
- [ ] [BODY-62] A `whole` outside BODY-61, or not a string, prints `body malformed: whole: whole reason must be one bounded non-empty line`, exit `2`, the same sentence for every invalid shape.

  ```
  whole = ""
  whole = "   "
  whole = " one lock"
  whole = "one\nlock"
  whole = "one\u0007lock"
  whole = 1
  # any reason over 512 characters
  ```

## Never

- `aco check -` never reads a file path, a live item, a dependency, the forge, or the state ref; it reads stdin and the repository's own storage pin only.
- No reader ever derives a blocker or a parent from the body: `Blocked by:` prose beside the block is documentation, and the `Parent: #<n>` line is read back by `aco cut`'s own orphan adoption alone.
- A rewrite of one block field never changes a byte outside the fence, but it does re-render the whole block interior canonically: schema key order, TOML-safe quoting, the fence's own newline convention.
- No reader guesses through a defect: a malformed body is refused by name, never treated as an empty or partial block.
- No reader maps one line form onto the other: a yes/no line and an option line are each read at their own index, and `yes` never reads as `A`.

## Examples

`Setup: bare-remote` is a fresh work repository whose `origin` is a local bare
repository with `main` at one commit, a git identity, `origin/HEAD`, and
`ACO_AGENT` set; `<remote>`, `<tmp>` and `<home>` are the runner's own paths.
Sessions whose stdin carries a fenced block use a four-backtick console fence.

### E-BODY-01 — the golden body, complete and valid

Setup: bare-remote, `storage = "github"` in a tracked `.aco/board.toml`

````console
$ aco check - <<'BODY'
Prose a reader may write freely.

```aco
version = 1
now = "Cut on 19.09.2026 from #320."
next = "Build the two contract specs."
done_when = "Both spec files exist and the lint probe is named."
```
BODY
body ok
exit 0
````

### E-BODY-02 — an unfilled skeleton is incomplete, not malformed

Setup: bare-remote, `storage = "github"`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = ""
next = ""
done_when = ""
```
BODY
2> body incomplete: Now, Next, Done when
exit 2
````

A block with only `done_when` left empty, as an untied cut writes it
(`specs/cut.spec.md` CUT-37), names that one key:

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Cut from #90"
next = "Build this slice; claim it with aco start."
done_when = ""
```
BODY
2> body incomplete: Done when
exit 2
````

### E-BODY-03 — a body with no block, and a claim against that item

Setup: bare-remote, `storage = "github"`, issue `#42` carrying that same body

````console
$ aco check - <<'BODY'
## Ziel
Prose only, no typed block.
BODY
2> body malformed: aco: no aco block
exit 2
$ aco claim 42 --scope README.md
2> ERROR: body malformed: aco: no aco block
exit 2
````

### E-BODY-04 — every defect at once, as an object

Setup: bare-remote, `storage = "github"`

````console
$ aco check - --json <<'BODY'
```aco
version = 2
now = "Something"
next = "Something"
done_when = "Something"
unknown_key = 1
```
BODY
{"ok": false, "reason": "malformed", "defects": ["body malformed: version: version must be exactly 1", "body malformed: unknown_key: unknown top-level key unknown_key"]}
exit 2
````

### E-BODY-05 — `[record]` is known only under the state-ref pin

Setup: bare-remote, `storage = "state-ref"` in a tracked `.aco/board.toml`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Build it."
done_when = "It is built."

[record]
title = "Body block contract"
state = "open"
labels = []
blocked_by = []
created_at = "2026-09-19T08:00:00Z"
updated_at = "2026-09-19T08:00:00Z"
```
BODY
body ok
exit 0
````

### E-BODY-06 — a slice title stays on one line

Setup: bare-remote, `storage = "github"`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Cut it."
done_when = "Every slice is cut."

[[slice]]
index = 1
title = "Line one\u000bLine two"
```
BODY
2> body malformed: slice[0].title: slice[0].title of row 1 holds U+000B; a slice title stays on one line
exit 2
````

### E-BODY-07 — a slice row's own `done_when`

Setup: bare-remote, `storage = "github"`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Cut it."
done_when = "Every slice is cut."

[[slice]]
index = 1
title = "Slice A"
done_when = "The parser reads the new key."
```
BODY
body ok
exit 0
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Cut it."
done_when = "Every slice is cut."

[[slice]]
index = 1
title = "Slice A"
done_when = "  "
```
BODY
2> body malformed: slice[0].done_when: slice[0].done_when must be a non-empty string
exit 2
````

### E-BODY-08 — `slice = []` stays a top-level key beside `[[expectation]]`

Setup: bare-remote, `storage = "github"`, issue `#90` whose block carries one
ruled `[[expectation]]` and one `[[slice]]` row, `index = 1` titled `Slice A`
with a `done_when`; after `aco cut 90` its block reads:

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Cut it."
done_when = "Every slice is cut."

slice = []

[[expectation]]
text = "A line"
ruling = "yes"
ruled_on = 2026-10-02
```
BODY
body ok
exit 0
````

### E-BODY-09 — a defect shows display controls as escapes

Setup: bare-remote, `storage = "github"`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Cut it."
done_when = "Every slice is cut."

"k\u001b]0;x\u0007" = 1
```
BODY
2> body malformed: k\x1b]0;x\x07: unknown top-level key k\x1b]0;x\x07
exit 2
````

### E-BODY-10 — a complete open option line

Setup: bare-remote, `storage = "github"`; its `card_hash` once ruled is `sha256:f7f1db4c507733e34c58d64de61fd482ad3d308db7ce3bf14bc503179c26519d`

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Decide it."
done_when = "It is decided."

[[expectation]]
text = "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt auf, der Take ist markiert, der Song bleibt offen."
question = "Soll dein Song beim Sprung zum Ursprungs-Take offen bleiben?"
problem = "Klickst du den Link zum Ursprungs-Take, ist dein geöffneter Song weg."
picture = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80"><style>.b{fill:#fff;stroke:#555}</style><rect class="b" x="1" y="1" width="198" height="78" rx="8"/></svg>"""
caption = "Der Browser springt selbst, dabei geht der Song verloren."
decision_kind = "product"
area = "Song-Seite"
topic = "Sprung zum Ursprungs-Take"
recommended = "A"
reason = "Behebt den Verlust; Strg- und Mittelklick bleiben normale Links."

[[expectation.option]]
name = "Song bleibt offen"
effect = "Die App springt selbst: v5 klappt auf, Take 7 ist markiert."
picture = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80"><style>.b{fill:#fff;stroke:#2a7}</style><rect class="b" x="1" y="1" width="198" height="78" rx="8"/></svg>"""
caption = "Der Song bleibt offen."
notice = "Du bleibst in deinem Song; Zurück führt zur Ansicht davor."
cost = "Mehr Navigationscode, abgesichert durch Browserfälle."
undo = "reversible"
undo_how = "jederzeit änderbar."
contract = "Ein normaler Klick oder Enter auf den Ursprungs-Link öffnet die Version in der App; der Song bleibt geöffnet."

[[expectation.option]]
name = "Bleibt wie heute"
effect = "Der Browser springt; der Song schließt sich."
same_as_today = true
notice = "Nach dem Klick wählst du den Song neu."
cost = "Keine."
undo = "reversible"
undo_how = "es wird nichts gebaut."
contract = "Der Ursprungs-Link bleibt ein normaler Browser-Sprung."
```
BODY
body ok
exit 0
````

### E-BODY-11 — option-line shape defects

Setup: bare-remote, `storage = "github"`. `<card>` stands for the projection
keys and line keys of E-BODY-12's card without its `ruling`, which with
E-BODY-12's two options prints `body ok`.

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Decide it."
done_when = "It is decided."

[[expectation]]
text = "Der Song bleibt beim Sprung offen."
default = "yes"
question = "Song offen lassen?"
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
caption = "Heute"
decision_kind = "kind"
area = "Song-Seite"
topic = "Sprung"
recommended = "C"
reason = "Behebt den Verlust."

[[expectation.option]]
letter = "A"
name = "Song bleibt offen"
effect = "Die App springt selbst."
picture = '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'
notice = "Du bleibst im Song."
cost = ""
undo = "maybe"
undo_how = "jederzeit."
contract = "Der Song bleibt offen."

[[expectation.option]]
name = "Wie heute"
effect = "Der Browser springt."
same_as_today = true
caption = "Wie heute"
notice = "Du wählst neu."
cost = "Keine."
undo = "final"
undo_how = "nichts gebaut."
```
BODY
2> body malformed: expectation[0].problem: expectation[0].problem is required
2> body malformed: expectation[0].decision_kind: expectation[0].decision_kind must be product, technical, data_risk, money, access, wording, or release
2> body malformed: expectation[0].recommended: expectation[0].recommended must be one of A, B
2> body malformed: expectation[0].default: expectation[0].default does not belong on an option line
2> body malformed: expectation[0].option[0].cost: expectation[0].option[0].cost must be a non-empty string
2> body malformed: expectation[0].option[0].undo: expectation[0].option[0].undo must be reversible or final
2> body malformed: expectation[0].option[1].contract: expectation[0].option[1].contract is required
2> body malformed: expectation[0].option[1].caption: expectation[0].option[1].caption needs a picture beside it
2> body malformed: expectation[0].option[0].picture: expectation[0].option[0].picture must not contain <script>
2> body malformed: expectation[0].option[0].letter: unknown key expectation[0].option[0].letter
exit 2
$ aco check - <<'BODY'
```aco
<card>
option = "A"
```
BODY
2> body malformed: expectation[0].option: expectation[0].option must be an array of tables
exit 2
$ aco check - <<'BODY'
```aco
<card>
option = [1, 2]
```
BODY
2> body malformed: expectation[0].option[0]: expectation[0].option[0] must be a table
2> body malformed: expectation[0].option[1]: expectation[0].option[1] must be a table
exit 2
$ aco check - <<'BODY'
```aco
<card>

[[expectation.option]]
name = "Song bleibt offen"
effect = "Die App springt selbst."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
notice = "Du bleibst im Song."
cost = "Mehr Code."
undo = "reversible"
undo_how = "jederzeit."
contract = "Der Song bleibt offen."
```
BODY
2> body malformed: expectation[0].option: expectation[0] must carry 2 to 4 options
exit 2
$ aco check - <<'BODY'
```aco
<card>
# its two options, today's and option A's picture each about 6000 bytes,
# option B's `same_as_today = true` replaced by a third such picture
```
BODY
2> body malformed: expectation[0]: expectation[0] pictures must total at most 16384 bytes
exit 2
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Decide it."
done_when = "It is decided."

[[expectation]]
text = "Ship it?"
default = "yes"
problem = "It waits."
```
BODY
2> body malformed: expectation[0].problem: expectation[0].problem belongs to an option line; this line has none
exit 2
````

### E-BODY-12 — the decided state of an option line

Setup: bare-remote, `storage = "github"`. The card, ruled `A` on 2026-10-28,
carries `card_hash = "sha256:6308916341e71850961411f654688124981f4854f6380da12f456a216ac97908"`
and `via = "board"`.

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Decide it."
done_when = "It is decided."

[[expectation]]
text = "Der Song bleibt beim Sprung offen."
ruling = "A"
question = "Song offen lassen?"
problem = "Der Song schließt sich."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
caption = "Heute"
decision_kind = "product"
area = "Song-Seite"
topic = "Sprung"
recommended = "A"
reason = "Behebt den Verlust."

[[expectation.option]]
name = "Song bleibt offen"
effect = "Die App springt selbst."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
notice = "Du bleibst im Song."
cost = "Mehr Code."
undo = "reversible"
undo_how = "jederzeit."
contract = "Der Song bleibt offen."

[[expectation.option]]
name = "Wie heute"
effect = "Der Browser springt."
same_as_today = true
notice = "Du wählst neu."
cost = "Keine."
undo = "final"
undo_how = "nichts gebaut."
contract = "Der Link bleibt."
```
BODY
2> body malformed: expectation[0].ruled_on: expectation[0] carries ruling without ruled_on
exit 2
````

The same card with `ruling = "C"`, `ruled_on = 2026-10-28`, the hash
above and `via = "board"` prints `2> body malformed: expectation[0].ruling: expectation[0].ruling must be one of A, B`, exit `2`.
Ruled `A` with `via = "phone"` it prints
`2> body malformed: expectation[0].via: expectation[0].via must be board, chat, or default`, exit `2`,
and without `via` it prints `2> body malformed: expectation[0].via: expectation[0] is ruled without via`, exit `2`.

### E-BODY-13 — a ruled card edited later

Setup: bare-remote, `storage = "github"`; E-BODY-12's card ruled `A` with
`ruled_on = 2026-10-28`, its hash and `via = "board"` prints `body ok`, exit `0`. Then its
`area` is edited:

````console
$ aco check - <<'BODY'
```aco
version = 1
now = "Open."
next = "Decide it."
done_when = "It is decided."

[[expectation]]
text = "Der Song bleibt beim Sprung offen."
ruling = "A"
ruled_on = 2026-10-28
card_hash = "sha256:6308916341e71850961411f654688124981f4854f6380da12f456a216ac97908"
via = "board"
question = "Song offen lassen?"
problem = "Der Song schließt sich."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
caption = "Heute"
decision_kind = "product"
area = "Song-Liste"
topic = "Sprung"
recommended = "A"
reason = "Behebt den Verlust."

[[expectation.option]]
name = "Song bleibt offen"
effect = "Die App springt selbst."
picture = '<svg xmlns="http://www.w3.org/2000/svg"/>'
notice = "Du bleibst im Song."
cost = "Mehr Code."
undo = "reversible"
undo_how = "jederzeit."
contract = "Der Song bleibt offen."

[[expectation.option]]
name = "Wie heute"
effect = "Der Browser springt."
same_as_today = true
notice = "Du wählst neu."
cost = "Keine."
undo = "final"
undo_how = "nichts gebaut."
contract = "Der Link bleibt."
```
BODY
2> body malformed: expectation[0].card_hash: expectation[0] was edited after its ruling; a changed ruling is a new line
exit 2
````
