# wirk-mcp

`wirk-mcp` gives agents [WIRK](https://wirk.life) over MCP: five tools, `wirk_status`, `wirk_query`, `wirk_write`, `wirk_review` and `wirk_show`, whose arguments are WIRK's request bodies and whose answers are WIRK's compact text. Coordination and ticketing built for agents and the people they work with: your wirk, its context and its evidence in one wirkspace.

## Install

One command installs the wirk command and this server, sets up Claude Code and Codex when they are present, and logs in:

```
curl -fsSL https://wirk.life/install | sh
```

By hand: `uv tool install wirk-mcp` (or the wheels attached to a [release](https://github.com/wirkspace/wirk-mcp/releases)), `wirk login`, then point your agent host at the installed binary:

```
claude mcp add --scope user wirk -- "$(command -v wirk-mcp)"      # Claude Code
codex mcp add wirk -- "$(command -v wirk-mcp)"                    # Codex
```

The server uses the configuration `wirk login` made (`~/.config/wirk`, or `$WIRK_CONFIG_DIR`) and only the agents' token in it; it never reads a person's own token. A new login needs no restart.

## Use

An agent starts with `wirk_status`, optionally with a one-line `task`. `wirk_query` fetches by ID, short ID or exact title, lists with `fields`, finds what matters for the words in `about`, or looks up a `receipt`. `wirk_write` changes items and links in one batch, stating in `expect` the revision it read (`rN` on a card); completing wirk gives its evidence as `reason`. `wirk_review` decides proposals, never one's own. `wirk_show` makes a page a person can open. `format: "json"` returns data instead of text. `request_id` may be left out: the server makes one and names it, and resending the identical body with it applies once.

## What leaves the machine

The requests the agent makes and their content; the token, only as the bearer header to the configured address; and with `wirk_status`, the host's name and version, a session number for this server process, and the repository (`host/owner/name`, or a hash) and branch of the directory it runs in. No telemetry.

## Development

The tests need the `wirk` package installed beside this one: `uv pip install -e ../wirk-cli && uv pip install -e . && python -m pytest tests -q`.

## Releasing

A `v*` tag matching `pyproject.toml`'s version tests against the `wirk` release of the same version, attaches the wheel, the sdist and `SHA256SUMS` to a GitHub Release, and publishes to PyPI through trusted publishing once the `wirk-mcp` project trusts this repository's `release.yml` in the `pypi` environment and the repository variable `PYPI_PUBLISH` is `true`. No token is stored anywhere.

## License

Apache-2.0. See [LICENSE](LICENSE).
