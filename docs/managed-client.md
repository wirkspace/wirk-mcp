# Managed client set for agent hosts

The normal human install is `uv tool install wirk` and, after `wirk-mcp` is on PyPI, `uv tool install wirk-mcp`. The `managed_client.py` release asset is for a host that must keep its CLI, MCP server and skill on one approved version. It adds no WIRK operation.

The release pipeline publishes `https://wirk.life/releases/current.json` only after testing the three public artifacts against the deployed service. The JSON has schema `1`, a unique `release_id`, and `cli`, `mcp` and `skill` entries. Each entry has the same `version`, an immutable HTTPS `url` and the artifact's SHA-256 digest. The CLI and MCP URLs name wheels; the skill URL names `SKILL.md`. Never point the manifest at a branch or a `latest` asset.

Install the `managed_client.py` asset at a stable, user-owned path and keep it executable. Point the host's `wirk-mcp` registration to a symlink named `wirk-mcp` that resolves to that file. A symlink named `wirk` provides the matched CLI. Point the host's skill discovery path at `~/.local/share/wirk-client/current/skill`. Back up existing registration and skill paths first. Preserve the user's WIRK token configuration; the launcher uses the current process environment and does not store tokens.

On each invocation the launcher fetches the approved manifest, verifies all three artifact hashes, installs the wheels in a versioned environment, checks installed package versions and skill authority text, then atomically switches `current`. It keeps the earlier versioned directory. A bad manifest, failed download, hash mismatch or install error exits clearly before switching. It does not silently run the older set when the approved manifest cannot be checked. Existing agent sessions may have already loaded an older skill; restart them after a release.

For rollback, the release owner republishes a previously tested manifest with a **new** `release_id` and immutable asset URLs. Before publication, recheck service compatibility and the live `wirk status` and MCP `wirk_status` identity. The prior release directory remains on disk for inspection. Do not retarget `current` by hand to an unapproved build.
