# Plan: let MCP-only agents attach files

WIRK work item `1d6d8ea2`; branch `mcp-file-attach`. Revised 15 October 2026 after Samuel's decision (message `10a06154`): an argument on `wirk_write`, not a new tool; the server uploads the named local files and writes in one step; a failed or partial upload applies nothing; MCP and CLI stay at parity. Plan only; it goes to adversarial review before any code.

## Problem

An agent with only MCP cannot store a file: no tool reaches `POST /v2/files`, and MCP has no way to carry bytes from the agent to the server. Logs, PDFs and recordings are lost from MCP-only sessions. Criteria:
- A session using only MCP attaches a local PDF and an audio file to a new item in one write, and the downloaded bytes match the originals' hashes.
- A failed or partial upload applies nothing.

## The argument

No new tool, no new key. The existing file keys of `wirk_write`'s operations also take local paths:
- `item.create` and `message.send`: `data.uploads`;
- `item.edit`: `patch.attach_uploads`.

Shape: a list of strings, each an upload ID (as today) or an absolute local path. A string starting with `/` or `~/` is a path (`~/` is expanded); upload IDs never start with either. IDs and paths may be mixed; order is kept.

```json
{"operations": [{"op": "item.create", "data": {"title": "Load test evidence", "body": "…",
  "uploads": ["/Users/sam/Downloads/report.pdf", "/Users/sam/Downloads/standup.m4a"]}}]}
```

Description text the agent sees. The three shapes in `operations` gain `uploads?` (create, message) and `attach_uploads?` (edit), and one sentence is appended:

> uploads/attach_uploads: upload IDs or absolute local file paths; the files are stored first, and if one fails nothing is written.

Limits, the CLI's own:
- **Size:** the service's `max_upload_bytes` per file (5 GiB by default), refused at the declare step with `upload_too_large` before any byte moves, exactly as `wirk upload` is.
- **Count:** no per-call cap of its own; core's write limits apply (32 operations, 4 MiB request, and only IDs reach `/v2/write`).
- **Types:** any regular file; core derives the media type from the base name, as for the CLI.
- **Which files:** the CLI's `readable()` check, shared (a regular file; never WIRK's own token or configuration, by device and inode). One addition for MCP only, below.

## Flow, inside one `wirk_write` call (wirk-mcp `server.py`)

1. **Find paths** in the keys above. None: the write is sent exactly as today.
2. **Check every path before any request:** absolute after `~/`; resolved through symlinks; no part of the resolved path starts with `.`; opened with the CLI's `readable()`. Any refusal returns an error naming the path, says nothing was sent, and makes no request.
3. **Store each file with the CLI's transfer**, in order, in the call's `workspace_id`: declare `{bytes, sha256}`; PUT the bytes to the signed link unless `present`; confirm with the base name and request ID `<request_id>/<operation>/<n>`; one retry on `upload_incomplete`, as the CLI does. The confirmed upload ID replaces the path.
4. **Write once:** `/v2/write` under the call's `request_id` (the server makes one if absent, as today), carrying only upload IDs.
5. **Answer.** Success: the write's receipt text, the same answer `wirk write --request` gives with those upload IDs. Failure in step 3 (`upload_too_large`, `not_authorized`, `files_unavailable`, `storage_failed`, `upload_mismatch`, `request_conflict` when a file changed between tries, `outcome_unknown` on a confirm): an error with the service's or storage's words for that file, then `Nothing was written. Resend the identical arguments with request_id R; files already stored are reused.` A refused write (for example `basis_changed`) is core's answer unchanged; core applies nothing.

The signed link never reaches the agent or the output; only the base name, size and SHA-256 reach WIRK, never the full path.

## Atomicity

- The write is never sent unless every path became an upload ID; core's write is atomic, and an unknown upload refuses the whole batch.
- Files confirmed before a failure stay stored and unattached, on no item. That is what happens today when `wirk upload` is not followed by a write. Correction to the brief: unattached uploads do not expire, for the CLI or anyone. Core has no sweeper, and the bucket's lifecycle expires only noncurrent object versions after 90 days.
- A resend with the same `request_id` repeats nothing: each declare finds the bytes (`present`, no PUT), each confirm returns the same upload ID under its derived request ID, and the write body is byte-identical, so core applies once or replays the receipt. Only a changed resend (new `request_id`) leaves one more unattached upload record of the same stored object.

## Parity with the CLI

The same limits and the same errors (the same codes from the same service steps, through the same shared functions), and the same resulting item: base names, media types, sizes and hashes as `wirk upload` then `wirk write --upload`. The CLI takes two commands, MCP one call.

What MCP cannot do that the CLI can, and why:
- **Hidden paths** (any part starting with `.`, such as `~/.ssh`, `~/.aws` or `.env`) are refused over MCP. A CLI agent already has a shell that can read them, so the CLI adds no reach. The MCP server may be the only file access an agent has, and secrets live in those places. The error says a person can use `wirk upload`.
- **No per-file description** (`wirk upload --description`); the item or message body says what the files are.
- **No store-without-write and no stdin**: MCP always attaches in the same call.

## Code

- **wirk-cli** `cli.py`: split `send_file` into `store(source, path, request_id, description, retry, service) -> envelope`, which prints nothing because stdout is the MCP channel and takes the retry wording as a parameter, and the CLI's wrapper that emits it. No CLI interface change. It ships in the next CLI release; wirk-mcp pins that exact version.
- **wirk-mcp** `server.py`: path detection, checks, the store loop and the failure text; `tools.json`: the description edits. No core change, no new route, tool or key.

## Schema budget (5,494 bytes, measured today: 5,494, no headroom; instructions 897 of 900, untouched)

- Adds about 157 bytes: the three `uploads?`/`attach_uploads?` keys (37) and the sentence (120).
- Cuts about 163 bytes of repeated text:
  - `wirk_status` format's "text (default) or json." (40);
  - `wirk_write` request_id becomes "Optional; named in the receipt." (62), since the `outcome_unknown` hint already gives the resend at the moment it matters;
  - `wirk_review` request_id's description (61), since `required` shows it is optional.
- The bound in `test_exactly_five_compact_tools` stays 5,494; the build measures the exact figure.

## Tests (RED first)

End to end against a real core: wirk-core's `create_app` in process on a scratch SQLite database, with the contract tests' object store that refuses any PUT whose bytes or signed headers differ. The test is wired as an httpx transport under wirk-mcp's in-process MCP client. Core is private, so the file starts with `pytest.importorskip("wirk_core.service")`. It runs locally with core installed into the venv at a recorded SHA; public CI skips it, and no private URL enters `pyproject.toml`.

1. **Criterion 1:** one `wirk_write` with a PDF and an `.m4a` path in `data.uploads` makes one item with two files. Downloading each through `/v2/files` gives bytes whose SHA-256 equals the originals'. Names are base names, media types are `application/pdf` and audio; the write body holds no path.
2. **Criterion 2:** the second path is missing, so no request is made at all, and no item or upload exists in core afterwards.
3. **Partial failure:** the store refuses the second PUT, so the error says nothing was written and names the request ID, and there is no item. Resending the identical arguments after the store recovers gives exactly one item, with no second PUT of the first file; a third resend replays the receipt.
4. **Limits:** with core's `max_upload_bytes` set to 1 KiB, a 2 KiB file is refused with `upload_too_large` and no write, the same code `wirk upload` gets on that file in the same test. Refused before any request: a relative path, a directory, a missing file, the agent token, a path under a dot-folder, and a symlink resolving into one.

Fast tests on the existing fake transport:

5. `attach_uploads` on `item.edit` and `uploads` on `message.send` take paths, and mixed IDs and paths keep their order.
6. A write without paths is byte-identical to today's.
7. Nothing is printed to stdout during a write with paths, and the person token is never opened (extends the existing test).
8. The budget holds, and the operations text names `uploads`, `attach_uploads` and "absolute local file paths".
9. wirk-cli: `store()` returns the confirmed envelope and prints nothing; the existing upload tests stay green.

**Acceptance trial:** a fresh session with the shell off and only the installed server attaches a real PDF and `.m4a` to a new labelled scratch item in one call, and `wirk download` hashes match `shasum -a 256`. A run with a missing second path leaves no item. It records calls and time, and also checks macOS privacy prompts on Downloads and Documents ("Operation not permitted" must surface as a plain refusal).

## Docs (for a separate docs writer, in the same release)

- wirk-mcp README: one sentence in Use; in "What leaves the machine", a named file's bytes go straight to storage and only its base name, size and SHA-256 reach WIRK.
- wirk-skill `SKILL.md`: one line under Write: attach files with `wirk upload` then `--upload`, or over MCP absolute paths in `uploads`/`attach_uploads`.
- wirk-site `docs/cli-and-mcp.md` line 143: replace "There is no MCP tool for files; use the CLI." with the path rule and the all-or-nothing sentence. `docs/write.md` lines 41, 67 and 69: note the path form for MCP.

## Estimate

wirk-mcp `server.py` +35 lines; `tools.json` net about −6 bytes; tests +170 lines (an e2e harness of about 60 lines plus tests). wirk-cli `cli.py` +6 lines and tests +15.

## Deliberately not built

- A sixth tool, base64 bytes in arguments, or signed links handed to the agent (rejected on 6 October).
- Allowed-folder configuration (`file-roots`): no new configuration; parity with the CLI plus the hidden-path rule instead.
- Paths in the CLI's `--upload`: the CLI already reaches the same item, and a CLI flag change is its own interface decision.
- Paths in `replace_files`, per-file descriptions over MCP, and downloads for MCP-only agents (their own item if wanted).
- A sweeper for unattached uploads: none exists for the CLI either; a separate backlog item if storage cost or privacy needs it.

No question remains for Samuel.
