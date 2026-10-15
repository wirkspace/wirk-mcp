"""The two criteria against a real core: wirk-core's app in process on a scratch database, and an object store that
keeps only bytes matching the size and checksum it signed. wirk-core is private, so this runs only where it is
installed (`uv pip install` a wirk-core checkout into the test environment); elsewhere it is skipped."""

import base64
import hashlib
import json
import sqlite3
from urllib.parse import urlencode, urlsplit

import httpx
import pytest

pytest.importorskip("wirk_core.service", reason="wirk-core is private: install a checkout to run these tests")
from fastapi.testclient import TestClient  # noqa: E402
from wirk_core.service import create_app  # noqa: E402

from conftest import TOKEN, URL  # noqa: E402
from wirk_mcp import server  # noqa: E402

WORKSPACE, SECOND = "wsp_" + "0c0ffee0" * 4, "wsp_" + "b" * 32
BUCKET = "fake-bucket.invalid"
PDF = b"%PDF-1.7\n" + bytes(range(256)) * 40
AUDIO = b"\x00\x00\x00\x20ftypM4A " + bytes(range(255, -1, -1)) * 60


class Objects:
    """Copied, cut down, from wirk-core's tests/support.py FakeObjects (not installed with wirk_core): the store
    refuses a PUT whose size or SHA-256 differs from what was signed."""

    def __init__(self):
        self.objects, self.signed, self.puts, self.refuse = {}, {}, [], set()

    def key(self, account, workspace, sha256):
        return f"accounts/{account}/{workspace}/{sha256}"

    def status(self):
        return {"ready": True}

    def key_arn(self, account):
        return f"arn:aws:kms:us-west-2:000000000000:key/{account[4:12]}"

    def put_url(self, key, size, sha256, arn):
        headers = {"x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha256)).decode(),
                   "x-amz-server-side-encryption": "aws:kms", "x-amz-server-side-encryption-aws-kms-key-id": arn}
        url = f"https://{BUCKET}/{key}?X-Amz-Signature=fake"
        self.signed[url] = {"size": size, "checksum": headers["x-amz-checksum-sha256"]}
        return {"url": url, "headers": headers, "expires_at": "2999-01-01T00:00:00Z"}

    def put(self, request) -> httpx.Response:
        data, signed = request.read(), self.signed[str(request.url)]
        self.puts.append(urlsplit(str(request.url)).path[1:])
        checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
        if len(self.puts) in self.refuse or (len(data), checksum) != (signed["size"], request.headers["x-amz-checksum-sha256"]):
            return httpx.Response(500)
        self.objects[urlsplit(str(request.url)).path[1:]] = {
            "data": data, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "kms": request.headers["x-amz-server-side-encryption-aws-kms-key-id"]}
        return httpx.Response(200)

    def head(self, key):
        found = self.objects.get(key)
        return {name: found[name] for name in ("bytes", "sha256", "kms")} if found else None

    def get_url(self, key, overrides):
        return {"url": f"https://{BUCKET}/{key}?{urlencode(overrides)}&X-Amz-Signature=fake", "expires_at": "2999-01-01T00:00:00Z"}

    def fetch(self, url):
        return self.objects[urlsplit(url).path[1:]]["data"]


class Wire(httpx.BaseTransport):
    """The MCP server's one connection: storage links go to the store, everything else to core."""

    def __init__(self, core, store):
        self.core, self.store, self.writes = core, store, 0

    def handle_request(self, request):
        if request.url.host == BUCKET:
            return self.store.put(request)
        self.writes += request.url.path == "/v2/write"
        answer = self.core.handle_request(request)  # the test client's stream type is not httpx's sync one
        return httpx.Response(answer.status_code, headers=answer.headers, content=answer.read())


@pytest.fixture
def core(tmp_path, home, mcp, monkeypatch):
    """A scratch core whose administrator holds the agent token; `call` runs a tool through the MCP client."""
    config = tmp_path / "service.json"
    config.write_text(json.dumps({
        "instance_id": "mcp-files-scratch", "database_path": str(tmp_path / "state.sqlite3"), "max_upload_bytes": 4096,
        "tokens": [{"principal_id": "admin", "sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}],
        "bootstrap": {"workspace_id": WORKSPACE, "name": "Scratch", "administrator_id": "admin"}}))
    config.chmod(0o600)
    store = Objects()
    with TestClient(create_app(config, objects=store), base_url=URL) as client:
        wire = Wire(client._transport, store)
        client.wire, client.store = wire, store
        client.db = sqlite3.connect(tmp_path / "state.sqlite3", isolation_level=None)

        def call(arguments):
            monkeypatch.setattr(server, "TRANSPORT", wire)
            server.SERVICES.clear()
            return mcp.session_call("wirk_write", arguments)
        client.call = call
        yield client


def fetch(core, title, workspace=WORKSPACE):
    answer = core.post("/v2/query", headers={"Authorization": f"Bearer {TOKEN}"},
                       json={"fetch": [title], "workspace_id": workspace, "format": "json"}).json()
    return answer["data"]["results"][0] if answer["ok"] else None


def downloaded(core, item, file_id, workspace=WORKSPACE):
    answer = core.post("/v2/files", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "download": {"item": item, "file": file_id}, "workspace_id": workspace, "format": "json"}).json()
    return core.store.fetch(answer["data"]["download"]["url"])


def evidence(tmp_path, *names, request_id="mcp-e2e-1", **extra):
    return {"request_id": request_id, "operations": [{"op": "item.create", "data": {
        "title": "Load test evidence", "uploads": [str(tmp_path / name) for name in names]}}], **extra}


@pytest.fixture
def originals(tmp_path):
    (tmp_path / "report.pdf").write_bytes(PDF)
    (tmp_path / "standup.m4a").write_bytes(AUDIO)
    (tmp_path / "big.wav").write_bytes(b"\x01" * 5000)
    return tmp_path


def test_one_write_attaches_a_pdf_and_audio_whose_downloads_match(core, originals):
    result = core.call(evidence(originals, "report.pdf", "standup.m4a"))
    assert not result.is_error, result.content[0].text
    item = fetch(core, "Load test evidence")
    files = {f["filename"]: f for f in item["attachments"]}
    assert set(files) == {"report.pdf", "standup.m4a"} and files["report.pdf"]["media_type"] == "application/pdf"
    for name, original in (("report.pdf", PDF), ("standup.m4a", AUDIO)):
        copy = downloaded(core, item["id"], files[name]["id"])
        assert hashlib.sha256(copy).hexdigest() == hashlib.sha256(original).hexdigest()


def test_a_missing_second_file_applies_nothing(core, originals):
    result = core.call(evidence(originals, "report.pdf", "gone.m4a"))
    assert result.is_error and fetch(core, "Load test evidence") is None
    assert core.db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0 and core.store.puts == []


def test_a_refused_second_upload_applies_nothing_and_an_identical_resend_finishes_once(core, originals):
    core.store.refuse = {2}
    result = core.call(evidence(originals, "report.pdf", "standup.m4a"))
    assert result.is_error and "mcp-e2e-1" in result.content[0].text and core.wire.writes == 0
    assert fetch(core, "Load test evidence") is None
    core.store.refuse = set()
    for _ in range(2):
        result = core.call(evidence(originals, "report.pdf", "standup.m4a"))
        assert not result.is_error, result.content[0].text
    assert len(core.store.puts) == 3  # report once, standup refused then stored; nothing again on the replay
    assert len(fetch(core, "Load test evidence")["attachments"]) == 2


def test_a_file_over_the_services_limit_is_refused_as_for_the_cli(core, originals):
    result = core.call(evidence(originals, "report.pdf", "big.wav"))
    assert result.is_error and "upload_too_large" in result.content[0].text and core.wire.writes == 0
    assert fetch(core, "Load test evidence") is None


def test_the_files_land_in_the_wirkspace_the_call_names(core, originals):
    account = core.db.execute("SELECT account_id FROM workspaces WHERE id=?", (WORKSPACE,)).fetchone()[0]
    core.db.execute("INSERT INTO workspaces (id, account_id, name) VALUES (?,?,?)", (SECOND, account, "Second"))
    core.db.execute("INSERT INTO enum_fields (workspace_id, key, revision, definition) "
                    "SELECT ?, key, revision, definition FROM enum_fields WHERE workspace_id=?", (SECOND, WORKSPACE))
    result = core.call(evidence(originals, "report.pdf", workspace_id=SECOND))
    assert not result.is_error, result.content[0].text
    assert fetch(core, "Load test evidence", SECOND) and core.store.puts[0].split("/")[2] == SECOND
