# wirk-mcp

`wirk-mcp` gives agents [WIRK](https://wirk.life) over MCP: five tools, `wirk_status`, `wirk_query`, `wirk_write`, `wirk_review` and `wirk_show`, whose arguments are WIRK's request bodies and whose answers are WIRK's compact text. Coordination and ticketing built for agents and the people they work with: your wirk, its context and its evidence in one wirkspace.

## Install

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to install the CLI from PyPI and the MCP server from its public GitHub release:

```
uv tool install wirk
uv tool install https://github.com/wirkspace/wirk-mcp/releases/download/v0.4.0/wirk_mcp-0.4.0-py3-none-any.whl
```

The commands install `wirk` and `wirk-mcp`, respectively. Version 0.4.0 of `wirk-mcp` is available from [GitHub Releases](https://github.com/wirkspace/wirk-mcp/releases/tag/v0.4.0), not PyPI. Both packages require Python 3.12 or later. If you need uv, use `brew install uv` with Homebrew or `pipx install uv` with pipx. Follow uv's PATH guidance so your shell can find both commands.

Authorize this machine, approve the code in your browser, and check the connection:

```
wirk login
wirk status
```

Then register the installed server with the host you use. First check that `command -v wirk-mcp` prints its path.

For Claude Code:

```
claude mcp add --scope user wirk -- "$(command -v wirk-mcp)"
```

For Codex:

```
codex mcp add wirk -- "$(command -v wirk-mcp)"
```

Start a new agent session after registration. Add the [WIRK skill](https://github.com/wirkspace/wirk-skill#install) separately. The Claude Code plugin is an alternative to manual MCP registration and skill copying; use one setup route to avoid duplicate tools. See [Getting started](https://wirk.life/docs/getting-started/) for the complete account and agent setup.

The server uses the configuration `wirk login` made (`~/.config/wirk`, or `$WIRK_CONFIG_DIR`) and only the agents' token in it; it never reads a person's own token. A new login needs no restart.

## Use

An agent starts with `wirk_status`, optionally with a one-line `task`. `wirk_query` fetches by ID, short ID or exact title, lists with `fields`, finds what matters for the words in `about`, or looks up a `receipt`. `wirk_write` changes items and links in one batch, stating in `expect` the revision it read (`rN` on a card); completing wirk gives its evidence as `reason`. Context changes apply when the agent may make them; otherwise they are refused with `requires_review` and the agent proposes them. Only people decide proposals, so an agent's `wirk_review` is refused (`not_authorized` for its own proposal, `person_required` for any other); the person decides at their own terminal with `wirk review ID@N accept --reason WHY --person` (see the [wirk command](https://github.com/wirkspace/wirk-cli#for-people)). `wirk_show` makes a page a person can open; it is not live on api.wirk.life yet and answers `views_unavailable`. `format: "json"` returns data instead of text. `request_id` may be left out: the server makes one and names it, and resending the identical body with it applies once.

## What leaves the machine

The requests the agent makes and their content; the token, only as the bearer header to the configured address; and with `wirk_status`, the host's name and version, a session number for this server process, and the repository (`host/owner/name`, or a hash) and branch of the directory it runs in. No telemetry.

## Development

The tests need the `wirk` package installed beside this one: `uv pip install -e ../wirk-cli && uv pip install -e . && python -m pytest tests -q`.

## Releasing

A `v*` tag matching `pyproject.toml`'s version tests against the `wirk` release of the same version, attaches the wheel, the sdist and `SHA256SUMS` to a GitHub Release, and publishes to PyPI through trusted publishing once the `wirk-mcp` project trusts this repository's `release.yml` in the `pypi` environment and the repository variable `PYPI_PUBLISH` is `true`. No token is stored anywhere.

## License

Apache-2.0. See [LICENSE](LICENSE).
