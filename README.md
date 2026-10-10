# wirk-mcp

`wirk-mcp` gives agents [WIRK](https://wirk.life) over MCP: five tools, `wirk_status`, `wirk_query`, `wirk_write`, `wirk_review` and `wirk_show`, whose arguments are WIRK's request bodies and whose answers are WIRK's compact text. Coordination and ticketing built for agents and the people they work with: your wirk, its context and its evidence in one wirkspace.

## Install

One command installs the wirk command and this server, sets up Claude Code and Codex when they are present, and logs in:

```
curl -fsSL https://wirk.life/install | sh
```

By hand: install the wheel attached to a [release](https://github.com/wirkspace/wirk-mcp/releases) (`uv tool install https://github.com/wirkspace/wirk-mcp/releases/download/v0.4.3/wirk_mcp-0.4.3-py3-none-any.whl`), run `wirk login`, then point your agent host at the installed binary. First check `claude mcp get wirk` or `codex mcp get wirk`: a server named wirk with another command is an earlier install. Replace it (Claude Code needs `claude mcp remove --scope user wirk` first; Codex's add replaces it), or skip the add when it already runs this binary:

```
claude mcp add --scope user wirk -- "$(command -v wirk-mcp)"      # Claude Code
codex mcp add wirk -- "$(command -v wirk-mcp)"                    # Codex
```

The server uses the configuration `wirk login` made (`~/.config/wirk`, or `$WIRK_CONFIG_DIR`) and only the agents' token in it; it never reads a person's own token. A new login needs no restart.

## Use

An agent starts with `wirk_status`, optionally with a one-line `task`. `wirk_query` fetches by ID, short ID or exact title, lists with `fields`, finds what matters for the words in `about`, or looks up a `receipt`. `wirk_write` changes items and links in one batch, stating in `expect` the revision it read (`rN` on a card); completing wirk gives its evidence as `reason`. Context changes apply when the agent may make them; otherwise they are refused with `requires_review` and the agent proposes them. `wirk_review` accepts, rejects or defers proposals when the agent's role may review; a background agent only proposes. `wirk_show` makes a page a person can open; it is not live on api.wirk.life yet and answers `views_unavailable`. `format: "json"` returns data instead of text. `request_id` may be left out: the server makes one and names it, and resending the identical body with it applies once.

## What leaves the machine

The requests the agent makes and their content; the token, only as the bearer header to the configured address; and with `wirk_status`, the host's name and version, a session number for this server process, and the repository (`host/owner/name`, or a hash) and branch of the directory it runs in. No telemetry.

## Development

The tests need the `wirk` package installed beside this one: `uv pip install -e ../wirk-cli && uv pip install -e . && python -m pytest tests -q`.

## Releasing

A `v*` tag matching `pyproject.toml`'s version tests against the `wirk` release of the same version, attaches the wheel, the sdist and `SHA256SUMS` to a GitHub Release, and publishes to PyPI through trusted publishing once the `wirk-mcp` project trusts this repository's `release.yml` in the `pypi` environment and the repository variable `PYPI_PUBLISH` is `true`. No token is stored anywhere.

## License

Apache-2.0. See [LICENSE](LICENSE).

### Automated publication

Push the exact reviewed version tags for the CLI, MCP and skill. Each existing Release workflow then tests and publishes its component; MCP and skill wait up to ten minutes for the matching CLI wheel and its identical PyPI distribution. Tags choose reviewed source; pushing main does not publish a release.

New GitHub releases stay prereleases until their downloaded public bytes match the build and a clean public installation passes. The shared publication workflow is pinned to an exact revision. Failures appear in Actions. Retry failed jobs to reuse the successful build artifacts: identical existing assets are retained, missing assets are uploaded, and differing bytes or a moved tag stop the run. Do not overwrite a published asset to make a retry pass.

The Release workflow's manual verification input checks an existing public tag without publishing. This publication automation does not update already-installed or running clients.
