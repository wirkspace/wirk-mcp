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
    cli = base / "cli-project"
    (cli / "src/wirk_cli").mkdir(parents=True)
    (cli / "src/wirk_cli/__init__.py").write_text("def main():\n    print('wirk 0.4.1')\n")
    (cli / "pyproject.toml").write_text("""[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"
[project]
name = "wirk"
version = "0.4.1"
requires-python = ">=3.12"
[project.scripts]
wirk = "wirk_cli:main"
[tool.hatch.build.targets.wheel]
packages = ["src/wirk_cli"]
""")
    for project in (cli, ROOT):
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(base), str(project)], check=True,
                       capture_output=True, text=True)
    skill = base / "SKILL.md"
    skill.write_text("---\nname: wirk\n---\nBackground agents never decide.\n")
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
    assert hashlib.sha256((home / "current/skill/SKILL.md").read_bytes()).hexdigest() == assets["skill"]["sha256"]
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


def test_tampered_cached_skill_is_rejected_before_exec(tmp_path, assets):
    approved = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, approved)
    assert result.returncode == 0, result.stderr
    current = (home / "current").resolve()
    (current / "skill/SKILL.md").write_text("altered")
    result, home = run(tmp_path, approved)
    assert result.returncode != 0
    assert "cached" in result.stderr.lower() or "hash mismatch" in result.stderr.lower()
    assert (home / "current").resolve() == current


def test_tampered_cached_executable_is_rejected_before_exec(tmp_path, assets):
    approved = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, approved)
    assert result.returncode == 0, result.stderr
    current = (home / "current").resolve()
    executable = current / "venv/bin/wirk-mcp"
    executable.write_text("altered")
    result, home = run(tmp_path, approved)
    assert result.returncode != 0
    assert "cached" in result.stderr.lower() or "hash mismatch" in result.stderr.lower()
    assert (home / "current").resolve() == current


def test_oversized_asset_preserves_current_release(tmp_path, assets):
    first = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, first)
    assert result.returncode == 0, result.stderr
    before = (home / "current").resolve()
    oversized = tmp_path / "SKILL.md"
    oversized.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    next_release = json.loads(json.dumps(first))
    next_release["release_id"] = "test-042"
    next_release["skill"] = file_asset(oversized)
    result, home = run(tmp_path, next_release)
    assert result.returncode != 0 and "too large" in result.stderr
    assert (home / "current").resolve() == before


def test_install_timeout_cleans_stage_and_preserves_current(tmp_path, assets, monkeypatch):
    first = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, first)
    assert result.returncode == 0, result.stderr
    before = (home / "current").resolve()
    import importlib.util
    script = ROOT / "scripts/managed_client.py"
    spec = importlib.util.spec_from_file_location("managed_client", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("WIRK_CLIENT_TEST_HOME", str(home))
    next_release = {**first, "release_id": "test-042"}
    def timeout(args, **kwargs):
        assert kwargs["timeout"] == module.INSTALL_WAIT
        raise subprocess.TimeoutExpired(args, module.INSTALL_WAIT)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        module.stage(home, next_release)
    assert (home / "current").resolve() == before
    assert not (home / "releases/test-042").exists()


def test_update_lock_wait_is_bounded(tmp_path, assets, monkeypatch):
    import fcntl
    import importlib.util
    script = ROOT / "scripts/managed_client.py"
    spec = importlib.util.spec_from_file_location("managed_client_lock", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "client-home"
    home.mkdir()
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps({"schema": 1, "release_id": "test-041", **assets}))
    monkeypatch.setenv("WIRK_CLIENT_TEST_HOME", str(home))
    monkeypatch.setenv("WIRK_CLIENT_TEST_MANIFEST", approved.as_uri())
    monkeypatch.setattr(module, "LOCK_WAIT", 0)
    monkeypatch.setattr(module.sys, "argv", ["wirk", "--version"])
    with (home / ".update.lock").open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError, match="lock timed out"):
            module.main()


def test_real_https_trickle_obeys_total_download_deadline(tmp_path, monkeypatch):
    import http.server
    import importlib.util
    import shutil
    import ssl
    import threading
    import time
    import urllib.request

    if not shutil.which("openssl"):
        pytest.skip("openssl needed for local HTTPS fixture")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True, timeout=30)
    class Trickler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "20")
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trickler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = ROOT / "scripts/managed_client.py"
    spec = importlib.util.spec_from_file_location("managed_client_tls", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = urllib.request.urlopen
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda url, timeout: original(
        url, timeout=timeout, context=ssl._create_unverified_context()))
    monkeypatch.setattr(module, "DOWNLOAD_WAIT", 0.1)
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            module.fetch(f"https://127.0.0.1:{server.server_port}/asset")
        assert time.monotonic() - start < 0.4
    finally:
        server.shutdown()


def test_tampered_installed_package_is_rejected(tmp_path, assets):
    approved = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, approved)
    assert result.returncode == 0, result.stderr
    current = (home / "current").resolve()
    package = next((current / "venv/lib").glob("python*/site-packages/wirk_cli/__init__.py"))
    package.write_text("def main():\n    print('altered code')\n")
    result, home = run(tmp_path, approved)
    assert result.returncode != 0
    assert (home / "current").resolve() == current


def test_missing_active_receipt_never_deletes_current_release(tmp_path, assets):
    approved = {"schema": 1, "release_id": "test-041", **assets}
    result, home = run(tmp_path, approved)
    assert result.returncode == 0, result.stderr
    current = (home / "current").resolve()
    (current / "manifest.json").unlink()
    broken = json.loads(json.dumps(approved))
    broken["skill"]["url"] = (tmp_path / "missing.md").as_uri()
    result, home = run(tmp_path, broken)
    assert result.returncode != 0
    assert (home / "current").resolve() == current
    assert (home / "current").exists()
