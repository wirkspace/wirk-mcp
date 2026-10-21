# wirk-mcp

`wirk-mcp` gives agents [WIRK](https://wirk.life) over MCP: five tools, `wirk_status`, `wirk_query`, `wirk_write`, `wirk_review` and `wirk_show`, whose arguments are WIRK's request bodies and whose answers are WIRK's compact text. Coordination and ticketing built for agents and the people they work with: your wirk, its context and its evidence in one wirkspace.

## Install

One command installs the wirk command and this server, sets up Claude Code and Codex when they are present, and logs in:

```
curl -fsSL https://wirk.life/install | sh
```

By hand, install the CLI and MCP server as separate tools from PyPI:

```
uv tool install wirk
uv tool install wirk-mcp
```

Installing `wirk-mcp` alone provides the server binary, not the `wirk` CLI command. Run `wirk login`, then point your agent host at the installed binary. First check `claude mcp get wirk` or `codex mcp get wirk`: a server named wirk with another command is an earlier install. Replace it (Claude Code needs `claude mcp remove --scope user wirk` first; Codex's add replaces it), or skip the add when it already runs this binary:

```
claude mcp add --scope user wirk -- "$(command -v wirk-mcp)"      # Claude Code
codex mcp add wirk -- "$(command -v wirk-mcp)"                    # Codex
```

Package releases are also listed on [GitHub](https://github.com/wirkspace/wirk-mcp/releases).

The server uses the configuration `wirk login` made (`~/.config/wirk`, or `$WIRK_CONFIG_DIR`) and only the agents' token in it; it never reads a person's own token. A new login needs no restart. In an agent chat it uses that chat's own token instead, the one `wirk login` in the chat made: the chat is recognised by the thread ID a Codex request carries (or `CODEX_THREAD_ID`) and by `CLAUDE_CODE_SESSION_ID` in the server's environment (Claude Code, in the terminal and the desktop app), never by a tool argument. Until the chat has run `wirk login`, its calls answer `actor_setup_required`.

## Use

For catch-ups about status, priorities or blockers, use `wirk_status` for breadth. Batch a few visible work and decision leads in the first `wirk_query`, then follow selected links or truncated details in the next before naming specific blockers, owners or next work. Cards and counts are leads; stop when evidence suffices and name gaps. Catch-ups are read-only and answered from WIRK: read the repository or other sources only to implement or when asked to verify, and otherwise offer to check. Old handoffs and age do not establish release or worker state. Direct MCP is preferred; the CLI also works.

An agent starts with `wirk_status`, optionally with a one-line `task`. `wirk_query` fetches by ID, short ID or exact title, lists with `fields`, finds what matters for the words in `about`, or looks up a `receipt`. `wirk_write` changes items and links in one batch, stating in `expect` the revision it read (`rN` on a card); completing wirk gives its evidence as `reason`. Context changes apply when the agent may make them; otherwise they are refused with `requires_review` and the agent proposes them. `wirk_review` accepts, rejects or defers proposals when the agent's role may review; a background agent only proposes. `wirk_show` returns a link to a live, read-only page for a person; anyone with the link can open it until it expires after 24 hours. `wirk_status` and `wirk_query` are annotated read-only. In `wirk_write`, `uploads` (on `item.create` and `message.send`) and `attach_uploads` (on `item.edit`) take upload IDs or absolute local file paths: the server stores each file first and sends the write only when every file is stored; set your own `request_id` when attaching files. `format: "json"` returns data instead of text. `request_id` may be left out: the server makes one and names it, and resending the identical body with it applies once.

## What leaves the machine

The requests the agent makes and their content; the token, only as the bearer header to the configured address; and with `wirk_status`, the host's name and version, a session number for this server process, and the repository (`host/owner/name`, or a hash) and branch of the directory it runs in. No telemetry.

## Development

The tests need the `wirk` package installed beside this one: `uv pip install -e ../wirk-cli && uv pip install -e . && python -m pytest tests -q`.

## Releasing

A release is a version bump merged to main with `Release: publish wirk-mcp <version>` in its squash body; the version must equal the `wirk==` pin in `pyproject.toml`. After the release check passes on that exact commit, the tag `v<version>` is created there; pushing main publishes nothing, and a tag is never moved. The tag's Release workflow waits up to ten minutes for the `wirk` release of the same version, tests against that public CLI wheel, attaches the wheel, the sdist and `SHA256SUMS` to a GitHub Release, and publishes to PyPI through trusted publishing; no token is stored anywhere.

Release `wirk` first: a tag whose matching `wirk` release does not exist fails and stays unpublished, and the next version is released in step instead of moving the tag. New GitHub releases stay prereleases until their downloaded public bytes match the build and a clean public installation passes. Retry failed jobs to reuse the successful build artifacts: identical existing assets are retained, missing assets are uploaded, and differing bytes or a moved tag stop the run. The Release workflow's manual verification input checks an existing public tag without publishing. Publication does not update already-installed or running clients.

## License

Apache-2.0. See [LICENSE](LICENSE).
