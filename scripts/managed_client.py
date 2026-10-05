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
import signal
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST = "https://wirk.life/releases/current.json"
WHEEL_PREFIXES = {"cli": "wirk-", "mcp": "wirk_mcp-"}
MAX_MANIFEST = 64 * 1024
MAX_ASSET = 16 * 1024 * 1024
DOWNLOAD_WAIT = 30
INSTALL_WAIT = 120
LOCK_WAIT = 10


def fetch(url: str, limit: int = MAX_ASSET) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("approved release URL contains forbidden components")
    if parsed.scheme != "https" and not (os.environ.get("WIRK_CLIENT_TEST_HOME") and parsed.scheme == "file"):
        raise ValueError("approved release asset must use HTTPS")
    def timed_out(_signal, _frame):
        raise TimeoutError("approved release download timed out")

    previous_handler = signal.signal(signal.SIGALRM, timed_out)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, DOWNLOAD_WAIT)
    try:
        chunks = []
        size = 0
        with urllib.request.urlopen(url, timeout=min(10, DOWNLOAD_WAIT)) as response:
            while True:
                chunk = response.read(min(65536, limit + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                size += len(chunk)
                if size > limit:
                    raise ValueError("approved release download is too large")
                chunks.append(chunk)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def approved_manifest() -> dict:
    url = os.environ.get("WIRK_CLIENT_TEST_MANIFEST", MANIFEST)
    data = json.loads(fetch(url, MAX_MANIFEST))
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def package_hash(release: Path, package: str) -> str:
    matches = list((release / "venv/lib").glob(f"python*/site-packages/{package}"))
    if len(matches) != 1:
        raise ValueError(f"installed {package} package missing")
    digest = hashlib.sha256()
    root = matches[0]
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            digest.update(str(path.relative_to(root)).encode() + b"\0")
            digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def installed_versions(release: Path) -> list[str]:
    return subprocess.check_output([str(release / "venv/bin/python"), "-c",
        "import importlib.metadata as m; print(m.version('wirk'), m.version('wirk-mcp'))"],
        text=True, timeout=INSTALL_WAIT).split()


def validate_cache(release: Path, manifest: dict, receipt: dict) -> None:
    if receipt.get("manifest") != manifest:
        raise ValueError("approved release ID was reused with different contents")
    files = {"skill": release / "skill/SKILL.md"}
    for key, prefix in WHEEL_PREFIXES.items():
        name = Path(urllib.parse.urlparse(manifest[key]["url"]).path).name
        if not name.startswith(prefix):
            raise ValueError(f"wrong {key} artifact name")
        files[key] = release / "wheels" / name
    for key, path in files.items():
        if sha256(path) != manifest[key]["sha256"]:
            raise ValueError(f"cached {key} hash mismatch")
    executables = receipt.get("executables", {})
    if set(executables) != {"wirk", "wirk-mcp"}:
        raise ValueError("cached executable receipt is incomplete")
    for name, expected in executables.items():
        if sha256(release / "venv/bin" / name) != expected:
            raise ValueError(f"cached {name} executable hash mismatch")
    packages = receipt.get("packages", {})
    if set(packages) != {"wirk_cli", "wirk_mcp"}:
        raise ValueError("cached package receipt is incomplete")
    for name, expected in packages.items():
        if package_hash(release, name) != expected:
            raise ValueError(f"cached {name} package hash mismatch")
    if installed_versions(release) != [manifest["cli"]["version"], manifest["mcp"]["version"]]:
        raise ValueError("cached WIRK versions differ from approved release")


def stage(home: Path, manifest: dict) -> Path:
    releases = home / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / manifest["release_id"]
    receipt = release / "manifest.json"
    if release.exists():
        if receipt.exists():
            validate_cache(release, manifest, json.loads(receipt.read_text()))
            return release
        if (home / "current").is_symlink() and (home / "current").resolve() == release:
            raise ValueError("active release receipt is missing")
        shutil.rmtree(release)  # an interrupted inactive stage was never activated
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
        subprocess.run(["uv", "venv", "--python", "3.12", str(venv)], check=True, stdout=subprocess.DEVNULL, timeout=INSTALL_WAIT)
        subprocess.run(["uv", "pip", "install", "--python", str(venv / "bin/python"),
                        *(str(wheel) for wheel in wheels)], check=True, stdout=subprocess.DEVNULL, timeout=INSTALL_WAIT)
        versions = installed_versions(release)
        if versions != [manifest["cli"]["version"], manifest["mcp"]["version"]]:
            raise ValueError("installed WIRK versions differ from approved release")
        executables = {name: sha256(venv / "bin" / name) for name in ("wirk", "wirk-mcp")}
        packages = {name: package_hash(release, name) for name in ("wirk_cli", "wirk_mcp")}
        receipt.write_text(json.dumps({"manifest": manifest, "executables": executables, "packages": packages}, sort_keys=True))
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
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("approved release update lock timed out")
                time.sleep(0.1)
        release = stage(home, manifest)
        activate(home, release)
    os.execv(str(home / "current/venv/bin" / name), [name, *sys.argv[1:]])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"WIRK approved client unavailable: {error}", file=sys.stderr)
        sys.exit(1)
