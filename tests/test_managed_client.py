"""The Codex launcher switches only after a complete, compatible release is installed."""

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def file_asset(path):
    return {"version": "0.4.1", "url": path.as_uri(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    base = tmp_path_factory.mktemp("client-assets")
    cli = ROOT.parent / "wirk-cli"
    for project in (cli, ROOT):
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(base), str(project)], check=True,
                       capture_output=True, text=True)
    skill = base / "SKILL.md"
    skill.write_bytes((ROOT.parent / "wirk-skill/skills/wirk/SKILL.md").read_bytes())
    return {"cli": file_asset(base / "wirk-0.4.1-py3-none-any.whl"),
            "mcp": file_asset(base / "wirk_mcp-0.4.1-py3-none-any.whl"), "skill": file_asset(skill)}


def run(tmp_path, manifest):
    home = tmp_path / "client-home"
    bin_path = tmp_path / "bin"
    bin_path.mkdir(exist_ok=True)
    launcher = ROOT / "scripts/managed_client.py"
    launcher.chmod(0o755)
    executable = bin_path / "wirk"
    if not executable.exists():
        executable.symlink_to(launcher)
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(manifest))
    env = {**os.environ, "WIRK_CLIENT_TEST_HOME": str(home), "WIRK_CLIENT_TEST_MANIFEST": path.as_uri()}
    result = subprocess.run([str(executable), "--version"], env=env, capture_output=True, text=True, timeout=180)
    return result, home


def test_approved_release_installs_cli_mcp_and_skill_as_one_set(tmp_path, assets):
    manifest = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, manifest)
    assert result.returncode == 0, result.stderr
    assert "wirk 0.4.1" in result.stdout
    assert (home / "current/venv/bin/wirk-mcp").exists()
    assert "Background agents never decide" in (home / "current/skill/SKILL.md").read_text()
    assert stat.S_IMODE((home / "current/manifest.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("failure", ["hash", "download", "mismatch"])
def test_failed_update_preserves_current_set_and_modes(tmp_path, assets, failure):
    first = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, first)
    assert result.returncode == 0, result.stderr
    before = (home / "current").resolve()
    mode = stat.S_IMODE((before / "manifest.json").stat().st_mode)
    next_release = json.loads(json.dumps(first))
    next_release["release_id"] = "test-042"
    if failure == "hash":
        next_release["skill"]["sha256"] = "0" * 64
    elif failure == "download":
        next_release["skill"]["url"] = (tmp_path / "missing.md").as_uri()
    else:
        next_release["mcp"]["version"] = "0.4.2"
    result, home = run(tmp_path, next_release)
    assert result.returncode != 0
    assert "WIRK approved client unavailable" in result.stderr
    assert (home / "current").resolve() == before
    assert stat.S_IMODE((before / "manifest.json").stat().st_mode) == mode
