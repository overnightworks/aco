# `aco mcp`

`aco mcp` is a stdio MCP server an agent host starts for one session. Its tool `read_inbox` gives that session the decisions waiting on the operator across every
repository under the configured root; its tool `ask` puts one decision card on an item there. It takes no flags and no `--repo`, starts from any working directory and writes only through `ask`: the CLI stays complete without it.
It speaks the protocol of the `initialize` era, revisions `2025-11-25` and `2025-06-18`. The items and lines it returns are the ones `specs/rulings.spec.md` owns (RUL-10),
so an agent holds the line index and the `card_hash` that `aco rule` takes. Which repositories exist and how the root is found is `specs/serve.spec.md`'s (ABRD-14, ABRD-108..ABRD-111).

## Behavior table

| state \ trigger | start | a message arrives | the `read_inbox` or `ask` call |
|---|---|---|---|
| the global `aco --repo OWNER/REPO` before `mcp` | MCP-01 | — | — |
| stdin ends | MCP-02 | — | — |
| the host closed the pipe | MCP-03 | — | — |
| a line that is no JSON, no object or no request | — | MCP-04 | — |
| a notification | — | MCP-05 | — |
| `initialize` | — | MCP-06 | — |
| `ping` | — | MCP-07 | — |
| `tools/list` | — | MCP-08 | — |
| `server/discover` or any other method | — | MCP-09 | — |
| an unknown tool or arguments | — | MCP-10 | — |
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
| a card that would leave the body malformed | — | — | MCP-26 |
| an unknown argument, a state key, or a `repository` or `item` of the wrong type | — | — | MCP-27 |
| the forge's check of the write answers `not verified` or `overwritten` | — | — | MCP-28 |

## Serving

- [ ] [MCP-01] The global `aco --repo OWNER/REPO` before `mcp` is refused `ERROR: aco mcp finds its repositories itself; --repo does not apply to it`, exit `2` (see E-MCP-01).
- [ ] [MCP-02] End of input ends the process, exit `0`; every message before it was answered.
- [ ] [MCP-03] A host that closed the pipe ends the process, exit `0`, with no traceback on stderr.
- [ ] [MCP-04] One message is one line holding one JSON object. Unparsable JSON is answered error `-32700`; an array (no batching), another JSON value or a non-request object, error `-32600`; each with a null `id`.
- [ ] [MCP-05] A message without an `id` is a notification and is never answered; an empty line is skipped.
- [ ] [MCP-06] `initialize` is answered with the client's `protocolVersion` if `2025-11-25` or `2025-06-18`, else `2025-11-25`, plus `tools`, `serverInfo` (`aco`, its version), `instructions` naming both tools.
- [ ] [MCP-07] `ping` is answered with the empty result.
- [ ] [MCP-08] `tools/list` lists `read_inbox` (no properties, `readOnlyHint` true) and `ask` (`repository`, `item`, a card's keys; `readOnlyHint` false, `destructiveHint` false, `idempotentHint` true).
- [ ] [MCP-09] `server/discover` and every other method are answered error `-32601`.
- [ ] [MCP-10] `tools/call` of an unknown tool, of `read_inbox` with arguments, or of `ask` with arguments that are no object, is answered error `-32602`.
- [ ] [MCP-20] Standard output carries only these answers, one per line; logs go to standard error; every child process reads the null device or only data aco pipes to it, never the host's stream.

## Reading the inbox

- [ ] [MCP-11] `read_inbox` answers `structuredContent` and the same JSON as text: `root`, per repository its `items` with their waiting lines or `unavailable` and a reason, and `unreadable` (see E-MCP-02).
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
- [ ] [MCP-26] A card that would leave the body malformed, a picture holding a code-fence line for one, is refused as in MCP-25 before anything is written.
- [ ] [MCP-27] An unknown argument, a state key (`asked_on`, `ruling`, `card_hash`, ...), a `repository` that is no string or an `item` that is no integer is a tool error naming each; nothing is written.
- [ ] [MCP-28] A write whose check answers `not verified` or `overwritten` is a tool error with that sentence; asking the same card again then answers the line if it stands, else writes it.

## Never

- `aco mcp` writes only through `ask`: one option line per call, into the one item it names and in that item's turn, never another line of it, another repository or the operator's configuration; `read_inbox` is read-only.
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
< {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"<the structured content>"}],"structuredContent":{"root":"<root>","repositories":[{"repository":"owner/a","items":[{"number":7,"lines":[{"index":1,"form":"options"}]}]},{"repository":"owner/b","unavailable":"the forge is down"}],"unreadable":[]},"isError":false}}
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
