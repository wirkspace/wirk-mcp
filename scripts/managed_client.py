#!/usr/bin/env python3
"""Launch one approved WIRK client set; refresh it atomically before each run.

Install this file at a stable path and invoke it as `wirk` or `wirk-mcp`.
The release pipeline owns https://wirk.life/releases/current.json.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST = "https://wirk.life/releases/current.json"
WHEEL_PREFIXES = {"cli": "wirk-", "mcp": "wirk_mcp-"}


def fetch(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("approved release URL contains forbidden components")
    if parsed.scheme != "https" and not (os.environ.get("WIRK_CLIENT_TEST_HOME") and parsed.scheme == "file"):
        raise ValueError("approved release asset must use HTTPS")
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read()


def approved_manifest() -> dict:
    url = os.environ.get("WIRK_CLIENT_TEST_MANIFEST", MANIFEST)
    data = json.loads(fetch(url))
    if data.get("schema") != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", data.get("release_id", "")):
        raise ValueError("invalid approved release manifest")
    for key in ("cli", "mcp", "skill"):
        item = data.get(key)
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")):
            raise ValueError(f"invalid {key} in approved release manifest")
        if not isinstance(item.get("url"), str) or not isinstance(item.get("version"), str):
            raise ValueError(f"incomplete {key} in approved release manifest")
    if len({data[key]["version"] for key in ("cli", "mcp", "skill")}) != 1:
        raise ValueError("approved release versions differ")
    return data


def stage(home: Path, manifest: dict) -> Path:
    releases = home / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / manifest["release_id"]
    receipt = release / "manifest.json"
    if release.exists():
        if receipt.exists():
            if json.loads(receipt.read_text()) != manifest:
                raise ValueError("approved release ID was reused with different contents")
            return release
        shutil.rmtree(release)  # an interrupted stage was never activated
    release.mkdir()
    try:
        wheels = []
        for key in ("cli", "mcp", "skill"):
            item = manifest[key]
            name = Path(urllib.parse.urlparse(item["url"]).path).name
            if key in WHEEL_PREFIXES and not name.startswith(WHEEL_PREFIXES[key]):
                raise ValueError(f"wrong {key} artifact name")
            if key == "skill" and name != "SKILL.md":
                raise ValueError("wrong skill artifact name")
            content = fetch(item["url"])
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError(f"{key} release hash mismatch")
            if key == "skill":
                (release / "skill").mkdir(exist_ok=True)
                (release / "skill/SKILL.md").write_bytes(content)
            else:
                install = release / "wheels"
                install.mkdir(exist_ok=True)
                wheel = install / name
                wheel.write_bytes(content)
                wheels.append(wheel)
        venv = release / "venv"
        subprocess.run(["uv", "venv", "--python", "3.12", str(venv)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["uv", "pip", "install", "--python", str(venv / "bin/python"),
                        *(str(wheel) for wheel in wheels)], check=True, stdout=subprocess.DEVNULL)
        versions = subprocess.check_output([str(venv / "bin/python"), "-c",
            "import importlib.metadata as m; print(m.version('wirk'), m.version('wirk-mcp'))"], text=True).split()
        if versions != [manifest["cli"]["version"], manifest["mcp"]["version"]]:
            raise ValueError("installed WIRK versions differ from approved release")
        skill = (release / "skill/SKILL.md").read_text()
        if "Only people decide proposals" in skill or "Background agents never decide" not in skill:
            raise ValueError("approved skill has obsolete review authority guidance")
        receipt.write_text(json.dumps(manifest, sort_keys=True))
        os.chmod(receipt, 0o600)
        return release
    except Exception:
        shutil.rmtree(release)
        raise


def activate(home: Path, release: Path) -> None:
    current = home / "current"
    if current.is_symlink() and current.resolve() == release:
        return
    pending = home / ".current-next"
    pending.unlink(missing_ok=True)
    pending.symlink_to(release)
    os.replace(pending, current)


def main() -> None:
    name = Path(sys.argv[0]).name
    if name not in ("wirk", "wirk-mcp"):
        raise ValueError("launcher must be invoked as wirk or wirk-mcp")
    home = Path(os.environ.get("WIRK_CLIENT_TEST_HOME", Path.home() / ".local/share/wirk-client"))
    manifest = approved_manifest()
    home.mkdir(parents=True, exist_ok=True)
    with (home / ".update.lock").open("a+b") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        release = stage(home, manifest)
        activate(home, release)
    os.execv(str(home / "current/venv/bin" / name), [name, *sys.argv[1:]])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"WIRK approved client unavailable: {error}", file=sys.stderr)
        sys.exit(1)
