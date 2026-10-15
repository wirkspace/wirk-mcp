# Plan: let MCP-only agents attach files

WIRK work item `1d6d8ea2`; branch `mcp-file-attach`. Revised 15 October 2026 after Samuel's decision (message `10a06154`): an argument on `wirk_write`, not a new tool; the server uploads the named local files and writes in one step; a failed or partial upload applies nothing; MCP and CLI stay at parity. Second revision after the plan review of PR 33 at d48a8b4.

## Problem

An agent with only MCP cannot store a file: no tool reaches `POST /v2/files`, and MCP carries no bytes from the agent to the server. Criteria:
- A session using only MCP attaches a local PDF and an audio file to a new item in one write, and the downloaded bytes match the originals' hashes.
- A failed or partial upload applies nothing.

## The argument

No new tool, no new key. The existing file keys of `wirk_write`'s operations also take local paths: `data.uploads` on `item.create` and `message.send`, and `patch.attach_uploads` on `item.edit`. Each is a list of strings. A string matching core's ID form `(upload_)?[0-9a-f]{6,32}` is an upload ID and passes through as today. Anything else is a path: `~/` is expanded, and it must then be absolute or it is refused locally, so a relative path never reaches core as an ID. Order is kept.

```json
{"request_id": "evidence-load-test-1", "operations": [{"op": "item.create", "data": {"title": "Load test evidence",
  "uploads": ["/Users/sam/Downloads/report.pdf", "/Users/sam/Downloads/standup.m4a"]}}]}
```

What the agent reads:
- The operation shapes gain `uploads?` (create, message) and `attach_uploads?` (edit).
- One sentence: "uploads/attach_uploads: upload IDs or absolute local file paths, stored first; if one fails nothing is written."
- `request_id` keeps "After an uncertain result, resend with that ID" and adds "set your own when attaching files" (B1 below).

Limits, the CLI's own:
- **Size:** the service's `max_upload_bytes` per file (5 GiB by default), refused at declare with `upload_too_large`.
- **Count:** no cap of MCP's own; core's write limits apply (32 operations, 4 MiB; only IDs reach `/v2/write`).
- **Types:** any regular file; core derives the media type from the name.
- **Which files:** the CLI's `readable()` only: a regular file, never WIRK's own token or configuration. There is no MCP-only rule. The host's per-call approval shows the full path.

## Flow, inside one `wirk_write` call (wirk-mcp `server.py`)

1. **Find paths** in the keys above. With none, the write is sent exactly as today.
2. **Check everything before any request.** Each path must be absolute and pass `readable()` (opened and closed at once). Each derived confirm ID `<request_id>/<operation index>/<n>` must fit core's 200 characters. A refusal names the path and says nothing was sent.
3. **Store each file**, one open at a time and opened by the path that was checked, with wirk-cli's `store()` in the call's `workspace_id`:
   - declare `{bytes, sha256}`;
   - PUT to the signed link unless the bytes are present;
   - confirm with the base name of the path as given, under the derived ID, retrying once on `upload_incomplete`.

   The declare and confirm bodies carry only the base name, size and hash. The upload ID replaces the path.
4. **Write once** under the call's `request_id`, with only upload IDs.
5. **Answer.** Success returns the write's receipt, the same answer `wirk write --request` gives with those IDs. A failure in step 3 returns the service's or storage's words, without CLI hints, then:
   - files already stored: "Stored but attached to nothing: a.pdf.";
   - then "Nothing was written. Resend the identical arguments with request_id R; files already stored are reused.";
   - on `request_conflict` (a path or file changed on a resend), "Nothing was written. Send the corrected arguments under a new request_id."

   A refused write (for example `basis_changed`) is core's answer unchanged, and core applies nothing.

**B1, cancellation and host timeouts.** `call_tool` runs `call` in a worker thread. A host that gives up (Codex's per-call default is about 60 seconds) cancels the request. `call_tool` then sets a per-call cancel flag and returns at once (`abandon_on_cancel`). The thread checks the flag between file chunks and before the write, and never sends the write once it is set. Files stored by then stay unattached. A resend under the agent's own `request_id` reuses them; a server-made ID is lost with the cancelled answer, hence the description line.

## Atomicity

The write is never sent unless every path became an upload ID; core's write is atomic, and an unknown upload refuses the whole batch. Files confirmed before a failure stay stored and unattached, as after a `wirk upload` never followed by a write. Such uploads do not expire today, for any client: core has no sweeper, and the bucket lifecycle covers only noncurrent versions. An identical resend repeats nothing:
- each declare finds the bytes, so there is no PUT;
- each confirm returns the same upload ID under the same derived ID;
- the write body is byte-identical, so core applies once or replays the receipt.

## Parity with the CLI

The same limits and the same errors, through the same shared functions (`readable()`, `store()`), and the same resulting item: names, media types, sizes and hashes as `wirk upload` then `wirk write --upload`. MCP takes one call where the CLI takes two. MCP cannot:
- give a per-file description (`--description`); the body says what the files are;
- store without writing, or read stdin.

An existing CLI gap, unchanged: `wirk upload` cannot choose a wirkspace (`store()` sends `workspace_id` only for MCP's caller). Paths in `wirk write --request` are a CLI interface question for Samuel separately, not built here.

## Code

- **wirk-cli** `cli.py`: split `send_file` into a silent `store(source, path, request_id, retry, service, description=None, workspace_id=None, fmt="json")` that returns the confirmed envelope, and the CLI wrapper that emits it. No CLI interface change. A PR on `mcp-file-attach` there.
- **wirk-mcp** `server.py`: classification, checks, the store loop, the cancel flag and the failure text. `tools.json`: the description edits. During the build wirk-mcp installs wirk-cli from the local branch. The `wirk==` pin moves to the released version at merge.
- No core change, route, tool or key.

## Schema budget

The bound in `test_exactly_five_compact_tools` is 5,494 bytes, measured at exactly 5,494. Instructions are 897 of 900 bytes and untouched.
- **Adds about 175 bytes:** the keys (37), the sentence (about 105) and the request_id clause (about 33).
- **Cuts the same from `wirk_status` and `wirk_review`:** `wirk_status` format's "text (default) or json." (40), `wirk_review` request_id's description (61), and trims of their prose that keep every wording test.
- The bound is not raised. The build records the exact figure.

## Tests (RED first)

Fast tests on the fake transport, covered by public CI:
1. Criterion 2: a missing second path sends no request at all.
2. Refused before any request:
   - a relative path, a directory, a missing file;
   - the agent token;
   - an over-long request_id;
   - a non-ID string like `report.pdf`.
3. Cancellation: the client times out mid-PUT, and no `/v2/write` is ever sent.
4. A write refused after the files were stored (`basis_changed`): core's answer, with nothing more to resend.
5. `request_conflict` on a changed resend gives the "new request_id" tail.
6. Two operations, each with files (create plus message, and an edit with `attach_uploads`): derived IDs and order are right, and mixed IDs and paths are kept.
7. `workspace_id` reaches declare and confirm.
8. Declare and confirm bodies carry only the base name, size and hash. No full path, signed URL or token appears in any body or answer.
9. A write without paths is byte-identical to today's, nothing prints to stdout, and the person token is never opened.
10. The budget holds, and the description names the keys.

End to end against a real core: wirk-core's `create_app` in process on a scratch SQLite database, under the in-process MCP client through an httpx transport. The object store is a copy of core's test `FakeObjects` (not installed with `wirk_core`, so about 30 lines are copied with a note); it checks the stored size and checksum. The file importorskips `wirk_core.service` and runs locally with core at a recorded SHA. Public CI skips it, and no private URL enters `pyproject.toml`. About 110 lines.
- E1, criterion 1: a PDF and an `.m4a` in one call make one item with two files; the downloaded SHA-256 equals the originals'.
- E2, partial failure: the second PUT is refused, so there is no item and the first file is stored unattached. An identical resend after recovery gives one item with no re-PUT, and a third resend replays the receipt.
- E3, limits: core's `max_upload_bytes` is set to 1 KiB, and a 2 KiB file gets `upload_too_large` with no write.
- E4, a principal in two wirkspaces: the files land in the named one.

wirk-cli: `store()` returns the envelope, prints nothing and sends `workspace_id` when given; the existing upload tests stay green.

**Acceptance trial:** a fresh session with the shell off and only the installed server attaches a real PDF and `.m4a` in one call, and `wirk download` hashes match. A missing second path leaves no item. The trial records calls and time, and how macOS privacy prompts surface.

## Docs (a separate docs writer, same release)

- wirk-mcp README: one sentence under Use. "What leaves the machine" gains that a named file's bytes go to storage and only its base name, size and hash reach WIRK.
- `server.py` docstring: arguments are the request bodies, except that paths become upload IDs.
- wirk-skill `SKILL.md`: one line.
- wirk-site `docs/cli-and-mcp.md` line 143: "Arguments are the HTTP request bodies" gains the path exception, and "There is no MCP tool for files; use the CLI." is replaced.
- wirk-site `docs/write.md` lines 41, 67, 69 and `docs/messages.md` line 36 (the uploads row): the path form for MCP.
- wirk-site `docs/errors.md`: remedies for `storage_failed` and `upload_too_large` in MCP terms.

## Estimate

wirk-mcp: `server.py` about +45 lines; `tools.json` net 0 bytes or less; fast tests about +120 and e2e about +110. wirk-cli: `cli.py` about +6 lines, tests about +20.

## Deliberately not built

- A sixth tool, base64 bytes, signed links for the agent, or allowed-folder configuration.
- Any MCP-only path rule.
- Paths in the CLI's write (Samuel's separate question).
- Paths in `replace_files`, per-file descriptions over MCP, MCP downloads, and a choice of wirkspace for `wirk upload`.
- A sweeper for unattached uploads (a backlog note in the PR body).
