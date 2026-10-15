"""Local files named in wirk_write's uploads and attach_uploads are stored first, then written once; else nothing is."""

import hashlib
import json
import threading
import time

import httpx
import pytest

from conftest import TOKEN, envelope

STORE = "https://storage.test"


def files(put_status=200, confirm=None, write=None, put=None):
    """The service and storage: declare gives a signed link, confirm an upload ID named after its request ID."""
    def answer(request):
        if request.url.host == "storage.test":
            if put:
                put(request)
            request.read()
            return httpx.Response(put_status)
        body = json.loads(request.content)
        if "upload" in body:
            return envelope(data={"present": False, "put": {"url": f"{STORE}/o/{body['upload']['sha256']}?X-Amz-Signature=s",
                                                            "headers": {"x-amz-checksum-sha256": "c"}, "expires_at": "2999"}})
        if "confirm" in body:
            return (confirm or upload_of)(body)
        return (write or (lambda b: envelope("Applied w-1 · created 5c1e7a90")))(body)
    return answer


def upload_of(body):
    return envelope(data={"upload": {"id": "upload_" + hashlib.sha256(body["request_id"].encode()).hexdigest()[:32]}})


def upload_id(request_id):
    return json.loads(upload_of({"request_id": request_id}).content)["data"]["upload"]["id"]


def bodies(requests):
    return [json.loads(r.content) for r in requests if r.url.host != "storage.test"]


@pytest.fixture
def pdf(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.7 report")
    (tmp_path / "standup.m4a").write_bytes(b"\x00\x00\x00 ftypM4A audio")
    return tmp_path


def create(*uploads, **extra):
    return {"request_id": "w-1", "operations": [{"op": "item.create", "data": {"title": "Evidence", "uploads": list(uploads)}}],
            **extra}


def test_paths_are_stored_then_written_once_with_only_names_sizes_and_hashes(mcp, pdf, capsys):
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf"), str(pdf / "standup.m4a")), files())
    sent = bodies(requests)
    assert [r.method for r in requests] == ["POST", "PUT", "POST", "POST", "PUT", "POST", "POST"]
    report = hashlib.sha256(b"%PDF-1.7 report").hexdigest()
    assert sent[0] == {"upload": {"bytes": 15, "sha256": report}, "format": "json"}
    assert sent[1] == {"request_id": "w-1/0/0", "confirm": {"filename": "report.pdf", "bytes": 15, "sha256": report},
                       "format": "json"}
    assert sent[3]["request_id"] == "w-1/0/1" and sent[3]["confirm"]["filename"] == "standup.m4a"
    assert requests[1].content == b"%PDF-1.7 report" and "authorization" not in requests[1].headers
    assert sent[4]["operations"][0]["data"]["uploads"] == [upload_id("w-1/0/0"), upload_id("w-1/0/1")]
    assert sent[4]["request_id"] == "w-1" and requests[6].url.path == "/v2/write"
    text = result.content[0].text
    assert text == "Applied w-1 · created 5c1e7a90" and not result.is_error
    for leak in (str(pdf), STORE, "X-Amz", TOKEN):
        assert leak not in json.dumps(sent) + text
    assert capsys.readouterr().out == ""


def test_a_missing_second_file_sends_nothing(mcp, pdf):
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf"), str(pdf / "gone.m4a")), files())
    assert requests == [] and result.is_error
    assert "gone.m4a" in result.content[0].text and "Nothing was sent" in result.content[0].text


@pytest.mark.parametrize("given", ["report.pdf", "./report.pdf", "upload_not-hex", "{dir}", "{dir}/gone.pdf",
                                   "{config}/agent-token"])
def test_a_bad_path_is_refused_before_any_request(mcp, pdf, home, given):
    result, requests = mcp.call("wirk_write", create(given.format(dir=pdf, config=home)), files())
    assert requests == [] and result.is_error and "Nothing was sent" in result.content[0].text
    assert TOKEN not in result.content[0].text


def test_a_request_id_too_long_to_name_the_uploads_is_refused_first(mcp, pdf):
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf"), request_id="w" * 197), files())
    assert requests == [] and result.is_error and "request_id" in result.content[0].text


def test_upload_ids_alone_are_sent_as_today(mcp):
    arguments = create("upload_" + "ab" * 16, "5c1e7a90")
    result, requests = mcp.call("wirk_write", arguments, files())
    assert bodies(requests) == [{**arguments, "format": "text"}]


def test_files_in_several_operations_keep_their_places(mcp, pdf, monkeypatch):
    monkeypatch.setenv("HOME", str(pdf))
    known = "upload_" + "cd" * 16
    arguments = {"request_id": "w-2", "operations": [
        {"op": "item.create", "ref": "n", "data": {"title": "T", "uploads": [str(pdf / "report.pdf"), known]}},
        {"op": "message.send", "data": {"body": "Evidence", "uploads": [str(pdf / "standup.m4a")]}},
        {"op": "item.edit", "id": "5c1e7a90", "patch": {"attach_uploads": [known, "~/report.pdf"]}}],
        "expect": {"5c1e7a90": 3}}
    result, requests = mcp.call("wirk_write", arguments, files())
    sent = bodies(requests)
    assert [b["request_id"] for b in sent if "confirm" in b] == ["w-2/0/0", "w-2/1/0", "w-2/2/1"]
    operations = sent[-1]["operations"]
    assert operations[0]["data"]["uploads"] == [upload_id("w-2/0/0"), known]
    assert operations[1]["data"]["uploads"] == [upload_id("w-2/1/0")]
    assert operations[2]["patch"]["attach_uploads"] == [known, upload_id("w-2/2/1")]
    assert sent[-1]["expect"] == {"5c1e7a90": 3} and not result.is_error


def test_the_wirkspace_named_in_the_call_receives_the_files(mcp, pdf):
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf"), workspace_id="wsp_9"), files())
    assert [b.get("workspace_id") for b in bodies(requests)] == ["wsp_9", "wsp_9", "wsp_9"]


def test_a_failed_upload_writes_nothing_and_names_what_was_stored(mcp, pdf):
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf"), str(pdf / "standup.m4a")), failing_second_put())
    text = result.content[0].text
    assert result.is_error and all(r.url.path != "/v2/write" for r in requests)
    assert "storage_failed" in text and "Stored but attached to nothing: report.pdf." in text
    assert "Nothing was written. Resend the identical arguments with request_id w-1" in text
    assert "wirk upload" not in text and "--request-id" not in text and STORE not in text


def failing_second_put():
    puts = []

    def answer(request):
        if request.url.host == "storage.test":
            request.read()
            puts.append(request)
            return httpx.Response(500 if len(puts) == 2 else 200)
        return files()(request)
    return answer


def test_a_changed_resend_is_told_to_use_a_new_request_id(mcp, pdf):
    conflict = envelope("Error request_conflict: This request_id already confirmed a different upload", ok=False,
                        errors=[{"code": "request_conflict", "message": "This request_id already confirmed a different upload"}],
                        status=409)
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf")), files(confirm=lambda body: conflict))
    text = result.content[0].text
    assert result.is_error and "request_conflict" in text and "new request_id" in text and "identical" not in text
    assert all(r.url.path != "/v2/write" for r in requests)


def test_a_write_refused_after_the_files_were_stored_is_the_services_answer(mcp, pdf):
    refused = envelope("Error basis_changed: 5c1e7a90 is at r4, not r3", ok=False,
                       errors=[{"code": "basis_changed", "message": "5c1e7a90 is at r4, not r3"}], status=409)
    result, requests = mcp.call("wirk_write", create(str(pdf / "report.pdf")), files(write=lambda body: refused))
    assert result.is_error and result.content[0].text == "Error basis_changed: 5c1e7a90 is at r4, not r3"
    assert [r.url.path for r in requests][-1] == "/v2/write"


def test_a_cancelled_call_never_writes(mcp, pdf):
    """A host that gives up mid-upload cancels the call; the thread still running must not send the write."""
    release, finished = threading.Event(), threading.Event()

    def held(request):
        release.wait(5)
        try:
            request.read()
        finally:
            finished.set()
    with pytest.raises(Exception):
        mcp.call("wirk_write", create(str(pdf / "report.pdf")), files(put=held), timeout=0.3)
    release.set()
    assert finished.wait(5)
    time.sleep(0.3)
    assert "/v2/write" not in [r.url.path for r in mcp.requests_seen]


def test_the_write_tool_says_paths_are_taken_and_how_to_retry(mcp):
    write = next(t for t in mcp.tools() if t.name == "wirk_write").input_schema["properties"]
    operations, request_id = write["operations"]["description"], write["request_id"]["description"]
    assert "uploads?" in operations and "attach_uploads?" in operations
    assert "upload IDs or absolute local file paths" in operations and "nothing is written" in operations
    assert "After an uncertain result, resend with that ID" in request_id and "attaching files" in request_id
