# Plan: let MCP-only agents attach files

Plan for Samuel's review, 6 October 2026. No code is changed. WIRK work item `1d6d8ea2`; branch `mcp-file-attach`.

## Problem

Original bytes move only through the CLI. `wirk upload` declares the size and SHA-256 to `POST /v2/files`, sends the bytes straight to the object store with the signed PUT it gets back, and confirms. The confirmation returns an upload ID, which `wirk write --upload` attaches as `uploads` on `item.create` or `attach_uploads` on `item.edit`. wirk-mcp's five tools have no route to `/v2/files`. An agent whose host gives it only MCP, such as a desktop chat app or a coding host with the shell turned off, cannot store a log, PDF or recording.

The item's acceptance criteria:
- A session using only MCP attaches a local PDF and an audio file to a new item in one write, and the downloaded bytes match the originals' hashes.
- A failed or partial upload applies nothing.

## What MCP offers (specification 2026-07-28, read 6 October)

- **Tool arguments are JSON** checked against `inputSchema`, and there is no binary input type. Binary data appears only in results, as base64 in image and audio `data` and in resource `blob`.
- **Resources go from server to client only**: list, read, templates and subscriptions. A client has no method for writing one.
- **Roots are deprecated** as of 2026-07-28 (SEP-2577). The stated migration is to pass directories or files "via tool parameters, resource URIs, or server configuration".
- **URL-mode elicitation** sends a person to a web page. It gives the agent no way to attach a file.
- **Clients SHOULD show tool inputs to the user before calling**, so a path in the arguments appears in the host's approval prompt.

## Candidates

| Design | Works for an MCP-only agent in a desktop app? | Verdict |
|---|---|---|
| 1. The agent names a path on its host, and the server reads and uploads the file | Yes, whenever wirk-mcp runs on the machine that holds the file, which is true of every stdio host today. Adds 153 bytes to `wirk_write` and no tool. | **Recommended** |
| 2. A base64 payload in a tool call, with a size cap | Only for small text. The model cannot read the bytes of a PDF or an audio file, and it would have to emit every byte as output tokens: 1 MiB becomes about 1.4 MB of base64. The 30 September HTTP contract also says "never base64 in JSON/MCP". | Rejected |
| 3. An MCP resource the agent writes | Impossible: the protocol has no client write. | Rejected |
| 4. A presigned URL returned for the agent's own HTTP client | An MCP-only agent has no HTTP client. It would also have to compute the SHA-256 and send the signed checksum and KMS headers exactly, and the URL is a 15-minute storage capability placed in the transcript. Core deliberately never prints it in text. | Rejected |
| 5. URL elicitation to a WIRK upload page | A person uploads, not the agent, and it needs a web page that does not exist. | Out of scope |

## Recommended design: paths in `uploads` and `attach_uploads`

The agent's call (`expect` and the other keys are unchanged):

```json
{"operations": [{"op": "item.create", "data": {"title": "Load test evidence", "body": "…",
  "uploads": ["~/Downloads/report.pdf", "~/Downloads/standup.m4a"]}}]}
```

What wirk-mcp does, for `wirk_write` only:

1. **Find the paths.** A path is any string in `data.uploads` or `patch.attach_uploads` that contains `/`, which upload IDs never do. A write with no path is sent exactly as today.
2. **Check every path before any byte moves:**
   - absolute once a leading `~/` is expanded;
   - inside an allowed folder after symlinks are resolved (see Privacy);
   - no part below that folder starts with `.`;
   - a regular file;
   - not WIRK's own token or configuration (the CLI's `readable` inode guard);
   - the total size within the cap, with at most 32 paths.

   Any refusal is an error, and no request is made.
3. **Store each file with the CLI's own transfer.** Declare `{bytes, sha256}`. Send the signed PUT unless the object is already stored. Confirm with the file's base name and request ID `<write request_id>/<operation index>/<n>`. That returns the upload ID.
4. **Write.** Each path is replaced with its upload ID, and `/v2/write` is posted under the same `request_id`. Core attaches the files atomically, and an unknown upload refuses the whole batch.
5. **On failure, stop before the write.** If any upload fails, nothing is written. The error says that nothing was applied and gives the `request_id` to resend the identical arguments with.
   - Uploads that were already confirmed stay stored but unattached.
   - A resend finds the bytes already stored (`present: true`), so nothing is sent again, and each confirm returns the same upload ID under its own request ID.
   - The write body is therefore byte-identical, and core replays the stored receipt.

**Code and releases.** No core change, route or tool. wirk-mcp gains about 40 lines in `server.py`. wirk-cli splits `send_file` in two: `store()` returns the confirmed answer and prints nothing, because stdout is the MCP channel, and the CLI's wrapper prints it. The split ships as wirk 0.4.1, and wirk-mcp pins it. The site's "There is no MCP tool for files" line, its "Later releases" row and the skill's MCP note change in the same release.

## Schema cost against the 5,120-byte budget

Measured through the MCP client, the way `test_exactly_five_compact_tools` measures it:
- **Today:** main is at exactly 5,120 bytes, with no headroom. The instructions are at 899 of 900 bytes, and this plan leaves them alone.
- **Added: 153 bytes.**
  - `uploads?` and `attach_uploads?` in the operation shapes: 27 bytes.
  - One sentence: 126 bytes. "uploads/attach_uploads take upload IDs or absolute file paths on this machine, stored first; a failed upload applies nothing."
- **Cut: 184 bytes of repeated text.**
  - `wirk_status` format's "text (default) or json.": 40 bytes. No other tool describes `format`.
  - `wirk_write`'s last sentence about uncertain results: 83 bytes. Its `request_id` description and the `outcome_unknown` hint already say it.
  - `wirk_review` request_id's "Optional; generated and named in the answer.": 61 bytes. `required` already shows it is optional.
- **Result:** 5,089 bytes, with 31 bytes of headroom. All 30 current tests pass with the change applied; it was tried locally and reverted.
- **A sixth tool** instead (`wirk_upload {path, description, request_id, workspace_id, format}`) measures 526 bytes, reaching 5,646. It breaks both the budget and the five-tool test.

## Size limits

- **Per file:** the service's `max_upload_bytes`. The declare step refuses a larger file with `upload_too_large` before any byte moves. Core's default is 5 GiB; decision 19 set 95 MiB for launch.
- **Per MCP call:** a proposed total of 95 MiB, checked from file sizes before any file is read. The call blocks while the bytes stream, and hosts time out tool calls. Above the cap, the refusal points to `wirk upload`, for a person or an agent with a shell.
- **At most 32 paths per call**, matching `max_write_operations`.
- **Requests to core stay small:** only IDs reach `/v2/write`, so decision 58's 4 MiB limit is untouched.
- **Plans:** decision 86's Pro list does not include files, and decision 65 puts them in Team. Attaching therefore works on every plan, with no Pro notice. Any storage quota the service enforces applies at the declare step, unchanged.

## Privacy

- **The bytes take the CLI's path.** The server reads only the agent token, never the person's. The signed PUT goes to `accounts/<account>/<wirkspace>/<sha256>` under the account's own KMS key, with the SHA-256 checksum signed (decisions 46 and 52). No byte passes through the WIRK service or the model's context.
- **The signed URL never reaches the agent.** It stays inside the server and is never printed, even in a storage error (`Service.storage`).
- **Only the base name leaves the machine.** The full path, which can contain a user name, is never sent to WIRK, so it is not stored in the write body or the receipt.
- **Which files the server may read.** The CLI reads any regular file except WIRK's own. Doing the same over MCP would widen what a host deliberately limited: an agent given no file access could read `~/.ssh` and post it to a wirkspace that everyone in it can read. So the server reads only inside allowed folders:
  - its working directory (the project, for coding hosts), unless that is `/` or the home folder;
  - folders a person lists, one absolute path per line, in `~/.config/wirk/file-roots`. This is a separate file because `wirk login` rewrites `config.json`.

  Dot-folders and dot-files below a root are refused, and symlinks are resolved before the check. This follows D14 of the 30 September interface plan, and "server configuration" is the specification's own replacement for roots.
- **The person sees the paths** in the host's approval prompt.

## Interface statement

**This is an interface change and needs Samuel's discussion before any code.** It adds no tool and no argument name. The existing `uploads` (`item.create`) and `attach_uploads` (`item.edit`) of `wirk_write` also accept absolute local paths, which wirk-mcp resolves. The wire to core is unchanged.

**Why existing operations can't carry it.** `wirk_write` already passes `uploads` through, but an MCP agent cannot get an upload ID: no tool reaches `/v2/files`, and nothing in MCP carries bytes from the agent to the server. All the agent can hand over is a name the server can open. A path in the field that already holds file references is the smallest form, and it keeps "one write" and "a failed upload applies nothing" in a single call.

**Why not a new tool.** It costs 526 bytes against zero headroom and adds a sixth tool against the principle of "status, query, write, review, show". It takes two calls where the criterion asks for one, and it leaves an unattached upload whenever an agent forgets the second call.

## RED tests

Tests 1–9 are in wirk-mcp `tests/test_tools.py` and use fake service and storage answers on the existing `MockTransport`. Test 10 is in wirk-cli.

1. **Paths are uploaded, then written once.** A PDF and an `.m4a` in an allowed folder go in `data.uploads`. Requests arrive in the order declare, PUT, confirm (twice), then `/v2/write`. Each PUT body equals the file's bytes. The confirm request IDs are `<rid>/0/0` and `<rid>/0/1`, with the base names as filenames. The write's `uploads` are the two upload IDs. No path, storage URL or token appears in the write body or the result text.
2. **`attach_uploads` on `item.edit` takes a path** in the same way.
3. **A failed upload applies nothing.** The second PUT answers 500. No `/v2/write` is sent, and the result is an error that names the `request_id` and says nothing was applied. It uses no CLI wording (`wirk upload`, `--request-id`).
4. **Bad paths are refused before any request** (`requests == []`): a relative path, a missing file, a directory, the agent token, a path outside every allowed folder, a path under a dot-folder in one, and a symlink leading out of one.
5. **A resend after `outcome_unknown` reuses everything.** The declare answers `present: true`, so no PUT is sent. The confirm request IDs are the same, and the second write body is byte-identical to the first.
6. **A write without paths is unchanged.** Upload IDs only produce one `/v2/write`, with the same body as today.
7. **Over the cap is refused from sizes alone.** No request is made, and the error names the cap and `wirk upload`.
8. **The budget holds.** The five-tool test stays at 5,120 bytes or under, and the operations text names `uploads`, `attach_uploads` and "absolute file paths".
9. **The person token is never opened** during a write with paths. This extends the existing test.
10. **`store()` returns the confirmed answer and prints nothing**, and the existing upload tests stay green.

**Acceptance trial.** A fresh session with the shell off and only the installed server attaches a real PDF and an `.m4a` to a new item in one `wirk_write`. `wirk download` of both files matches `shasum -a 256` of the originals. A run whose second path is missing leaves no item. The trial uses labelled scratch data, and records calls and time.

**Not yet exercised; the trial checks both:**
- Whether each desktop host runs stdio servers with the person's file permissions. macOS privacy prompts for Desktop, Documents and Downloads may refuse the read, which surfaces as "Operation not permitted".
- Agents whose files live in a VM sandbox see paths the host does not have. The refusal says the path must exist on the machine running wirk-mcp.

## Samuel's decisions

1. **The interface change:** paths in `uploads` and `attach_uploads`, over MCP only (recommended), or a sixth tool instead.
2. **The budget:** the three wording cuts above (recommended), or a budget raised above 5,120 bytes.
3. **Which files the server may read:**
   - (a) the working directory plus `file-roots`, with dot-paths refused (recommended);
   - (b) `file-roots` only, with no default (D14 as written);
   - (c) any readable file, like the CLI.
4. **The per-call cap:** 95 MiB (recommended), or another figure.
5. **Unattached uploads after a failed write:** keep them, since a retry reuses them (recommended; there is no sweeper today), or ask core for a sweeper.
6. **The path form has no per-file description and no paths in `replace_files`.** The item body says what the files are.
7. **Kept separate:** CLI parity (paths in `wirk write --upload`) and downloads for MCP-only agents (the 30 September `save`) each get their own item.
