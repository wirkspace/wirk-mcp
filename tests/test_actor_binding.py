"""Only the host request envelope selects the locally enrolled actor credential."""

import uuid

from conftest import TOKEN, URL, envelope
from wirk_cli.client import actor_base, actor_path, save_actor_current
from wirk_mcp import server

THREAD_A = str(uuid.UUID(int=21))
THREAD_B = str(uuid.UUID(int=22))
CHILD = "wirk_" + "c" * 43


def test_host_metadata_selects_actor_and_tool_arguments_cannot_override(mcp, home):
    first, requests = mcp.call("wirk_status", {}, meta={"threadId": THREAD_A})
    assert first.is_error and "actor_setup_required" in first.content[0].text and requests == []
    base = actor_base(URL, ("thread", THREAD_A))
    path = actor_path(base, "alice-agents", "alice")
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_text(CHILD)
    path.chmod(0o600)
    save_actor_current(base, URL, "alice-agents", "alice")
    result, requests = mcp.call("wirk_query", {"threadId": THREAD_B}, lambda request: envelope("actor"),
                                meta={"threadId": THREAD_A})
    assert not result.is_error and requests[0].headers["authorization"] == f"Bearer {CHILD}"
    other, requests = mcp.call("wirk_query", {}, meta={"threadId": THREAD_B})
    assert other.is_error and "actor_setup_required" in other.content[0].text and requests == []
    shared, requests = mcp.call("wirk_query", {})
    assert not shared.is_error and requests[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_upload_and_final_write_keep_one_request_service(monkeypatch, home):
    chosen = []

    class FakeService:
        def post(self, *args, **kwargs):
            chosen.append(("write", self))
            return {"ok": True, "errors": [], "text": "done"}

    active = FakeService()
    monkeypatch.setattr(server, "service", lambda actor_id=None: active)

    def files(body, cancelled, service):
        chosen.append(("files", service))
        return None

    monkeypatch.setattr(server, "store_files", files)
    text, failed = server.call("wirk_write", {"request_id": "one", "operations": []}, None,
                               __import__("threading").Event(), THREAD_A)
    assert (text, failed) == ("done", False)
    assert chosen == [("files", active), ("write", active)]


def test_concurrent_requests_keep_their_own_service(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    class Fake:
        def __init__(self, name):
            self.name = name

        def same(self, other):
            return self.name == other.name

    a_wrote, b_wrote = threading.Event(), threading.Event()

    class RacingCache(list):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if value[0].name == "a":
                a_wrote.set()
                assert b_wrote.wait(5)
            else:
                b_wrote.set()

    monkeypatch.setattr(server, "SERVICES", RacingCache())
    monkeypatch.setattr(server, "connect", lambda transport, actor_id=None: Fake(actor_id))
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(server.service, "a")
        assert a_wrote.wait(5)
        b = pool.submit(server.service, "b")
        assert a.result().name == "a"
        assert b.result().name == "b"
