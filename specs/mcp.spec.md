# `aco mcp`

`aco mcp` is a stdio MCP server an agent host starts for one session. Its first tool, `read_inbox`, gives that session the decisions waiting on the operator across every
repository under the configured root. It takes no flags and no `--repo`, starts from any working directory and writes nothing: the CLI stays complete without it.
It speaks the protocol of the `initialize` era, revisions `2025-11-25` and `2025-06-18`. The items and lines it returns are the ones `specs/rulings.spec.md` owns (RUL-10),
so an agent holds the line index and the `card_hash` that `aco rule` takes. Which repositories exist and how the root is found is `specs/serve.spec.md`'s (ABRD-14, ABRD-108..ABRD-111).

## Behavior table

| state \ trigger | start | a message arrives | the `read_inbox` call |
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

## Serving

- [ ] [MCP-01] The global `aco --repo OWNER/REPO` before `mcp` is refused `ERROR: aco mcp finds its repositories itself; --repo does not apply to it`, exit `2` (see E-MCP-01).
- [ ] [MCP-02] End of input ends the process, exit `0`; every message before it was answered.
- [ ] [MCP-03] A host that closed the pipe ends the process, exit `0`, with no traceback on stderr.
- [ ] [MCP-04] One message is one line holding one JSON object. Unparsable JSON is answered error `-32700`; an array (no batching), another JSON value or a non-request object, error `-32600`; each with a null `id`.
- [ ] [MCP-05] A message without an `id` is a notification and is never answered; an empty line is skipped.
- [ ] [MCP-06] `initialize` is answered with the client's `protocolVersion` when it is `2025-11-25` or `2025-06-18`, else `2025-11-25`, plus the `tools` capability, `serverInfo` (`aco`, its version), `instructions`.
- [ ] [MCP-07] `ping` is answered with the empty result.
- [ ] [MCP-08] `tools/list` lists `read_inbox` with an input schema that has no properties and the annotation `readOnlyHint` true.
- [ ] [MCP-09] `server/discover` and every other method are answered error `-32601`.
- [ ] [MCP-10] `tools/call` of another tool, or of `read_inbox` with arguments, is answered error `-32602`.
- [ ] [MCP-20] Standard output carries only these answers, one per line; the process writes its logs to standard error, and every child process it starts reads the null device as its input.

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

## Never

- `aco mcp` never writes to an item, a repository or the operator's configuration: `read_inbox` is read-only.
- It never answers a refusal as an empty inbox: a missing config file, a bad root and finding no repository are tool errors (MCP-15, MCP-16).
- It never prints anything but protocol messages on standard output (MCP-20).
- It never answers a notification (MCP-05).
- It never lists a line that is with its head or already decided (MCP-12).

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
