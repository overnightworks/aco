# `aco mcp`

`aco mcp` is a stdio MCP server an agent host starts for one session. Its tool `read_inbox` gives that session the decisions and the steps waiting on the operator across every
repository under the configured root; its tool `ask` puts one decision card on an item there; its tool `record_answer` records the answer the operator gave in the chat on a card's option line; its tool `step` marks a step only the operator can take. It takes no flags and no `--repo`, starts from any working directory and writes only through `ask`, `record_answer` and `step`: the CLI stays complete without it.
It speaks the protocol of the `initialize` era, revisions `2025-11-25` and `2025-06-18`. The items and lines it returns are the ones `specs/rulings.spec.md` owns (RUL-10),
so an agent holds the line index and the `card_hash` that `aco rule` takes. Which repositories exist and how the root is found is `specs/serve.spec.md`'s (ABRD-14, ABRD-108..ABRD-111).

## Behavior table

| state \ trigger | start | a message arrives | the `read_inbox`, `ask`, `record_answer` or `step` call |
|---|---|---|---|
| the global `aco --repo OWNER/REPO` before `mcp` | MCP-01 | — | — |
| stdin ends | MCP-02 | — | — |
| the host closed the pipe | MCP-03 | — | — |
| a line that is no JSON, no object or no request | — | MCP-04 | — |
| a notification | — | MCP-05 | — |
| `initialize` | — | MCP-06 | — |
| `ping` | — | MCP-07 | — |
| `tools/list` | — | MCP-08, MCP-38 | — |
| `server/discover` or any other method | — | MCP-09 | — |
| an unknown tool or arguments that are no object | — | MCP-10 | — |
| an open option line | — | — | MCP-11 |
| a ruled, returned, withdrawn or yes/no line | — | — | MCP-12 |
| an item left with no waiting line | — | — | MCP-13 |
| an item a non-member wrote | — | — | MCP-14 |
| a missing or malformed config file, no root, a relative root or one that is no directory | — | — | MCP-15 |
| no repository found | — | — | MCP-16 |
| a repository whose read fails | — | — | MCP-17 |
| a directory under the root that cannot be read | — | — | MCP-18 |
| a call after another call, or after a refusal | — | — | MCP-19 |
| a card on an open item a member wrote | — | — | MCP-21 |
| the same card asked again | — | — | MCP-22 |
| a card asked after its line was withdrawn | — | — | MCP-23 |
| a repository not found, or an item missing, a pull request, malformed, closed or a non-member's | — | — | MCP-24 |
| a card value the grammar refuses, a card rule broken, or an item with an incomplete body | — | — | MCP-25 |
| a card whose picture holds a code-fence line | — | — | MCP-26 |
| an unknown argument, a state key, or a `repository` or `item` of the wrong type | — | — | MCP-27 |
| the forge's check of the write answers `not verified` or `overwritten` | — | — | MCP-28 |
| an open option line and the operator's chat answer | — | — | MCP-29, MCP-30 |
| an answer in the operator's own words | — | — | MCP-31 |
| a repository not found, or an item missing, a pull request or malformed, a line out of range, ruled, withdrawn or a yes/no line, a changed card, a letter not on the card | — | — | MCP-32 |
| a closed item, or one a non-member wrote | — | — | MCP-33 |
| a line with its head | — | — | MCP-34 |
| an unknown argument, or a value of the wrong type, or not exactly one of `option` and `other`, or a blank `other` | — | — | MCP-35 |
| the forge's check of the answer's write answers `not verified` or `overwritten` | — | — | MCP-36 |
| `read_inbox` with arguments | — | — | MCP-37 |
| an open item a member wrote that carries the label `needs-operator` | — | — | MCP-39, MCP-41 |
| such an item whose body has no readable block | — | — | MCP-40 |
| such an item a non-member wrote, or one the store could not read | — | — | MCP-42 |
| several such items in one repository, or one that also has a waiting line | — | — | MCP-43 |
| a step on an open item a member wrote | — | — | MCP-44, MCP-46 |
| the same step call again | — | — | MCP-45 |
| a step with a title that no open item holds | — | — | MCP-47 |
| a step with a title that an open item a member wrote already holds with that step | — | — | MCP-48 |
| a padded `step` or `title` | — | — | MCP-49 |
| a step on a repository not found, or an item missing, a pull request, malformed, closed or a non-member's | — | — | MCP-50 |
| a step in a repository under `state-ref` storage | — | — | MCP-51 |
| a step whose body check answers `not verified` or `overwritten` | — | — | MCP-52 |
| a step whose label fails after the body is written or the item opened | — | — | MCP-53 |
| a new item whose issue type the forge did not set | — | — | MCP-54 |
| an unknown argument, a wrong type, not exactly one of `item` and `title`, or a blank `step` or `title` | — | — | MCP-55 |

## Serving

- [ ] [MCP-01] The global `aco --repo OWNER/REPO` before `mcp` is refused `ERROR: aco mcp finds its repositories itself; --repo does not apply to it`, exit `2` (see E-MCP-01).
- [ ] [MCP-02] End of input ends the process, exit `0`; every message before it was answered.
- [ ] [MCP-03] A host that closed the pipe ends the process, exit `0`, with no traceback on stderr.
- [ ] [MCP-04] One message is one line holding one JSON object. Unparsable JSON is answered error `-32700`; an array (no batching), another JSON value or a non-request object, error `-32600`; each with a null `id`.
- [ ] [MCP-05] A message without an `id` is a notification and is never answered; an empty line is skipped.
- [ ] [MCP-06] `initialize` is answered with the client's `protocolVersion` if `2025-11-25` or `2025-06-18`, else `2025-11-25`, plus `tools`, `serverInfo` (`aco`, its version), `instructions` naming all four tools.
- [ ] [MCP-07] `ping` is answered with the empty result.
- [ ] [MCP-08] `tools/list` lists `read_inbox` (`readOnlyHint` true), `ask` (`destructiveHint` false), `record_answer`, `step` (`destructiveHint` true); the last three: `readOnlyHint` false, `idempotentHint` true.
- [ ] [MCP-09] `server/discover` and every other method are answered error `-32601`.
- [ ] [MCP-10] `tools/call` of an unknown tool, or of any tool with arguments that are no object, is answered error `-32602`.
- [ ] [MCP-20] Standard output carries only these answers, one per line; logs go to standard error; every child process reads the null device or only data aco pipes to it, never the host's stream.

## Reading the inbox

- [ ] [MCP-11] `read_inbox` answers `structuredContent` and the same JSON as text: `root`, per repository its `items` and `steps`, or `unavailable` and a reason, and `unreadable` (see E-MCP-02).
- [ ] [MCP-12] A line waits on the operator when it is an option line neither ruled, nor returned to its head, nor withdrawn; no other line is listed.
- [ ] [MCP-13] An item left with no waiting line is not listed; a repository left with none is listed with no `items`.
- [ ] [MCP-14] Only items a member of the repository wrote are read (ABRD-06).
- [ ] [MCP-15] A missing or malformed config file, one without `root`, a relative `root` or a `root` that is no directory is a tool result with `isError` true naming the file, never an empty inbox (see E-MCP-03).
- [ ] [MCP-16] Finding no repository is a tool result with `isError` true that names the root, never an empty inbox.
- [ ] [MCP-17] A repository whose read fails is listed with `unavailable` and its reason; the others are still read (see E-MCP-02).
- [ ] [MCP-18] A directory under the root that cannot be read is listed in `unreadable` by its path with its reason, never skipped.
- [ ] [MCP-19] Every call scans the root afresh and reads the repositories concurrently, in discovery's order; a refusal or unexpected failure is a tool error, the server keeps running and the next call succeeds.

## Asking a card

The card is the option line `specs/body-block.spec.md` owns (BODY-84..BODY-99): `text`, the line keys and `options`, with no state key.

- [ ] [MCP-21] `ask` appends one option line, dated today in UTC, to the open item, and answers `repository`, `item`, `written` true and the line as RUL-10 prints it (see E-MCP-04).
- [ ] [MCP-22] The same card asked again writes nothing: `ask` answers `written` false and the line already there, the first when several match, with its ruling or return (see E-MCP-05).
- [ ] [MCP-23] A withdrawn line never matches a card: asking after its withdrawal appends a new line.
- [ ] [MCP-24] A repository not found, an item missing, a pull request, malformed, closed or written by a non-member is a tool error with the refusal's sentence; nothing is written (see E-MCP-06).
- [ ] [MCP-25] A card value the grammar refuses, a card breaking BODY-96..BODY-99 or an item whose body is incomplete is a tool error naming every defect; nothing is written (see E-MCP-07).
- [ ] [MCP-26] A card whose picture holds a code-fence line is stored: the body keeps its one `aco` block and the picture reads back unchanged.
- [ ] [MCP-27] An unknown argument, a state key (`asked_on`, `ruling`, `card_hash`, ...), a `repository` that is no string or an `item` that is no integer is a tool error naming each; nothing is written.
- [ ] [MCP-28] A write whose check answers `not verified` or `overwritten` is a tool error with that sentence; asking the same card again then answers the line if it stands, else writes it.

## Recording an answer

- [ ] [MCP-29] `record_answer` rules `line` as `aco rule --via chat` does, from `option` or `other` and the shown `card_hash`; it answers `repository`, `item`, the line as RUL-10 prints it and `open` (see E-MCP-08).
- [ ] [MCP-30] The answer binds like a board ruling: `read_inbox` drops the line, `aco rulings` shows it ruled with `via` `chat`, the board shows it decided and `aco next` no longer calls the item unruled.
- [ ] [MCP-31] An `other` is stored as given, whatever characters it holds; one that holds a line separator never ends the item's block, and the stored answer reads back equal.
- [ ] [MCP-32] Every refusal of `aco rule --via chat` holds: it is a tool error with the refusal's sentence and nothing is written, a repeat on a ruled line included (see E-MCP-09).
- [ ] [MCP-33] A closed item and an item a non-member wrote are ruled, as `aco rule` rules them.
- [ ] [MCP-34] A line with its head is ruled by the answer and loses `returned_on` and `returned_note`.
- [ ] [MCP-35] An unknown argument (`via` is none), a wrong type, not exactly one of `option` and `other`, or a blank `other` is a tool error naming each; nothing is read or written (see E-MCP-10).
- [ ] [MCP-36] A write whose check answers `not verified` or `overwritten` is a tool error with that sentence; the answer stands unless the sentence says it was overwritten in the meantime.
- [ ] [MCP-37] `read_inbox` called with any argument is a tool error `read_inbox takes no arguments`; without arguments it answers the inbox as before.
- [ ] [MCP-38] No tool schema has a top-level `oneOf`, `anyOf` or `allOf`; `record_answer` takes `repository`, `item`, `line`, `card_hash`, `option` or `other`, no `via`; `step` requires `repository`, `step`.
- [ ] [MCP-39] An open item that carries the label `needs-operator`, in any letter case, is a step: `steps` lists its `number`, `title` and `step`, the `next` of its block (see E-MCP-11).
- [ ] [MCP-40] A step whose body has no readable block, or a malformed one, is listed with `step` null; it is never left out and its title is not given as the step.
- [ ] [MCP-41] `steps` is present in every repository that was read, an empty list when none waits; a repository listed with `unavailable` has no `steps`.
- [ ] [MCP-42] Only items a member of the repository wrote are steps, as for cards (MCP-14); an item the store could not read is no step.
- [ ] [MCP-43] Steps come by descending item number; an item with the label and a waiting line is in `items` and in `steps`; one listing of a repository's open items serves both.

## Marking a step

`step` takes `repository`, `step` and exactly one of `item` and `title`.

- [ ] [MCP-44] `step` with an open `item` a member wrote writes `step` as its block's `next`, then sets the label `needs-operator`; it answers `repository`, `item`, `step` and `created` false (see E-MCP-12).
- [ ] [MCP-45] The same call again writes no body and sets the label again; it answers the same, so a repeat finishes a call whose label failed.
- [ ] [MCP-46] The rewritten body keeps every other field of the block, every ruling and every byte outside the block; the body is written before the label, both in the item's turn.
- [ ] [MCP-47] `step` with a `title` that no open item holds opens one item of kind task whose body names `step` as its `next`, sets the label and answers `created` true; `read_inbox` lists it (see E-MCP-13).
- [ ] [MCP-48] A `title` that an open, readable item a member wrote holds with that exact `next`, labelled or not, marks it (the highest number of several) and answers `created` false; another step opens one. An item whose title or `next` changed since the lookup is left as it is, judged as its turn reads it, and a new item opens.
- [ ] [MCP-49] `step` and `title` are stripped before use; the stored `next` and the title matched are the stripped text.
- [ ] [MCP-50] A repository not found, an item missing, a pull request, malformed, closed or written by a non-member is a tool error with the refusal's sentence; nothing is written (see E-MCP-14).
- [ ] [MCP-51] A repository under `state-ref` storage is refused before any item is read or written, naming `aco item edit` as the way (see E-MCP-15).
- [ ] [MCP-52] A body write whose check answers `not verified` or `overwritten` is a tool error with that sentence and sets no label; the same call again finishes it.
- [ ] [MCP-53] A label that fails after the body is written or the item opened is a tool error naming the item and the forge's reason; the same call again sets it (see E-MCP-16).
- [ ] [MCP-54] A new item whose issue type the forge did not set is a tool error naming the issue; the same call again sets the label and the type stays unset, to be set on the forge by hand.
- [ ] [MCP-55] An unknown argument, a wrong type, not exactly one of `item` and `title`, or a blank `step` or `title` is a tool error naming each; nothing is read or written (see E-MCP-17).

## Never

- `aco mcp` writes only through `ask`, `record_answer` and `step`: `ask` and `record_answer` one line per call, `step` one item's `next` in that item's turn, or one new item, per call, never another repository or the operator's configuration; `read_inbox` is read-only.
- `step` never removes the label `needs-operator`: the head does, once the operator says the step is done.
- `record_answer` never checks that the operator spoke: it records what the agent says he answered, and the forge's edit history is the record after the fact.
- It never answers a refusal as an empty inbox: a missing config file, a bad root and finding no repository are tool errors (MCP-15, MCP-16).
- It never prints anything but protocol messages on standard output (MCP-20).
- It never answers a notification (MCP-05).
- `read_inbox` never lists a line that is with its head or already decided (MCP-12); `ask` answers a line that stands whatever its state (MCP-22).

## Examples

`Setup: test-forge` is a root holding the checkouts `owner/a` and `owner/b`, whose items live in a file-backed forge; each request is one line on standard input and each answer one line on standard output.

### E-MCP-01 -- the global `--repo` does not apply to `mcp`

Setup: none

```console
$ aco --repo overnightworks/aco mcp
2> ERROR: aco mcp finds its repositories itself; --repo does not apply to it
exit 2
```

### E-MCP-02 -- one repository waits, one is down

Setup: `owner/a` holds item `#7` with one open option line; the forge of `owner/b` fails its listing with `the forge is down`

```text
> {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_inbox"}}
< {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"root":"<root>","repositories":[{"repository":"owner/a","items":[{"number":7,"lines":[{"index":1,"form":"options"}]}],"steps":[]},{"repository":"owner/b","unavailable":"the forge is down"}],"unreadable":[]},"isError":false}}
```

The item and line objects carry every key `aco rulings --json` prints (RUL-10); only the keys shown are repeated here.

### E-MCP-03 -- a config file that does not exist

Setup: `<config home>/aco/config.toml` does not exist

```text
> {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"read_inbox"}}
< {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"<config home>/aco/config.toml does not exist; create it with root = \"<absolute path>\""}],"isError":true}}
```

The other refusals read as in E-ABRD-17 and E-ABRD-18; each is a tool error, and the next call after the fix answers the inbox.

### E-MCP-04 -- a card asked on an open item

Setup: `owner/a` holds the open item `#7`, written by a member, with no option line; today is `2026-11-08` in UTC

```text
> {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"ask","arguments":{"repository":"owner/a","item":7,"text":"<text>","question":"<question>","options":["<2 to 4 option objects>"],"...":"the other line keys"}}}
< {"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"repository":"owner/a","item":7,"written":true,"line":{"index":1,"form":"options","asked_on":"2026-11-08"}},"isError":false}}
```

The line carries every key `aco rulings --json` prints (RUL-10); only the keys shown are repeated here. `aco rulings 7` and `read_inbox` list it as open.

### E-MCP-05 -- the same card again

Setup: as E-MCP-04, after its call; the same arguments are sent again

```text
< {"jsonrpc":"2.0","id":6,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"repository":"owner/a","item":7,"written":false,"line":{"index":1,"form":"options","ruling":null}},"isError":false}}
```

The item's body is unchanged. Once the operator has ruled the line, the same answer carries its `ruling`.

### E-MCP-06 -- an item that is closed

Setup: `owner/a` holds item `#7`, closed

```text
< {"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"item 7 is closed; a card on it would show nowhere"}],"isError":true}}
```

An item a non-member wrote answers `item 7 was not written by a member; its cards are not listed`, a repository the scan did not find `no repository owner/x found; read_inbox lists them`.

### E-MCP-07 -- a card value of the wrong type

Setup: as E-MCP-04, with `text` sent as a list

```text
< {"jsonrpc":"2.0","id":8,"result":{"content":[{"type":"text","text":"body malformed: expectation[0].text: expectation[0].text must be a non-empty string"}],"isError":true}}
```

An item with an empty `now`, `next` or `done_when` answers `body incomplete: Now`, naming each missing section, and a card whose `problem` runs past 20 words the BODY-97 sentence; nothing is written.

### E-MCP-08 -- the operator's answer recorded

Setup: `owner/a` holds the open item `#7` whose line 1 is an open option line with the options `A` and `B`; `<hash>` is its `card_hash` as `read_inbox` lists it; today is `2026-11-08` in UTC

```text
> {"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"record_answer","arguments":{"repository":"owner/a","item":7,"line":1,"card_hash":"<hash>","option":"A"}}}
< {"jsonrpc":"2.0","id":9,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"repository":"owner/a","item":7,"line":{"index":1,"form":"options","ruling":"A","ruled_on":"2026-11-08","via":"chat"},"open":0},"isError":false}}
```

The line carries every key `aco rulings --json` prints (RUL-10); only the keys shown are repeated here. `open` counts the lines of the item still open.

### E-MCP-09 -- the same answer again

Setup: as E-MCP-08, after its call; the same arguments are sent again

```text
< {"jsonrpc":"2.0","id":10,"result":{"content":[{"type":"text","text":"line 1 is already ruled; a changed ruling is a new line"}],"isError":true}}
```

The item's body is unchanged. A `card_hash` that no longer matches the card answers `line 1 changed since its card was shown; show it again and rule what it shows now`.

### E-MCP-10 -- arguments that do not fit

Setup: as E-MCP-08, with `line` sent as a string and both `option` and `other` given

```text
< {"jsonrpc":"2.0","id":11,"result":{"content":[{"type":"text","text":"line must be an integer; give exactly one of option and other"}],"isError":true}}
```

Nothing is read or written; a blank `other` answers `other must not be blank`.

### E-MCP-11 -- an item that waits on a step only the operator can take

Setup: `owner/a` holds item `#9` titled `Rotate the key`, labelled `needs-operator`, whose block has `next = "Rotate the deploy key in the host's settings."`

```text
> {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"read_inbox"}}
< {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"root":"<root>","repositories":[{"repository":"owner/a","items":[],"steps":[{"number":9,"title":"Rotate the key","step":"Rotate the deploy key in the host's settings."}]}],"unreadable":[]},"isError":false}}
```

An item labelled the same whose body holds no readable block is listed with `"step":null`.

### E-MCP-12 -- a step marked on an open item

Setup: `owner/a` holds the open item `#9`, written by a member, with a complete body

```text
> {"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"step","arguments":{"repository":"owner/a","item":9,"step":"Rotate the deploy key in the host's settings."}}}
< {"jsonrpc":"2.0","id":12,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"repository":"owner/a","item":9,"step":"Rotate the deploy key in the host's settings.","created":false},"isError":false}}
```

The block's `next` is the step and the item carries `needs-operator`, so E-MCP-11's `read_inbox` lists it. The same call again answers the same and writes no body.

### E-MCP-13 -- a step on a new item

Setup: as E-MCP-12, with no open item titled `Rotate the key`

```text
> {"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":"step","arguments":{"repository":"owner/a","title":"Rotate the key","step":"Rotate the deploy key in the host's settings."}}}
< {"jsonrpc":"2.0","id":13,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"repository":"owner/a","item":10,"step":"Rotate the deploy key in the host's settings.","created":true},"isError":false}}
```

The new item `#10` is a task labelled `needs-operator`; sent again, the call marks `#10` and answers `created` false.

### E-MCP-14 -- a step on a closed item

Setup: `owner/a` holds item `#7`, closed

```text
< {"jsonrpc":"2.0","id":14,"result":{"content":[{"type":"text","text":"item 7 is closed; a step on it would show nowhere"}],"isError":true}}
```

An item a non-member wrote answers `item 7 was not written by a member; its steps are not listed`.

### E-MCP-15 -- a repository under `state-ref` storage

Setup: `owner/a` is pinned to `storage = "state-ref"`

```text
< {"jsonrpc":"2.0","id":15,"result":{"content":[{"type":"text","text":"owner/a keeps its items in state-ref storage, where a step cannot be labelled; write it into the item's next with aco item edit"}],"isError":true}}
```

Nothing was read or written.

### E-MCP-16 -- a label the forge refused

Setup: as E-MCP-12, and the forge refuses the label with `HTTP 403`

```text
< {"jsonrpc":"2.0","id":16,"result":{"content":[{"type":"text","text":"#9 holds the step, but the label needs-operator was not set: HTTP 403; repeat the same call to set it once that cause is gone"}],"isError":true}}
```

The step stands in the item's `next`. The same call, sent once the cause is gone, writes no body and sets the label.

### E-MCP-17 -- arguments that do not fit

Setup: as E-MCP-12, with both `item` and `title` given and `step` blank

```text
< {"jsonrpc":"2.0","id":17,"result":{"content":[{"type":"text","text":"give exactly one of item and title; step must not be blank"}],"isError":true}}
```

Nothing is read or written.
