"""An in-process MCP client talking to the server, and a fake WIRK service behind it."""

import json

import anyio
import httpx
import pytest
from mcp import Client
from mcp_types import Implementation

from wirk_mcp import server

URL = "https://wirk.test"
TOKEN = "wirk_" + "a" * 43


def envelope(text="done", *, ok=True, errors=(), data=None, status=200):
    body = {"ok": ok, "errors": list(errors), "notices": [], "page": {"complete": True, "next_cursor": None}}
    body.update({"data": data} if data is not None else {"text": text})
    return httpx.Response(status, json=body)


@pytest.fixture
def home(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir(mode=0o700)
    (directory / "config.json").write_text(json.dumps({"service_url": URL}))
    token = directory / "agent-token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    monkeypatch.setenv("WIRK_CONFIG_DIR", str(directory))
    monkeypatch.chdir(tmp_path)
    return directory


@pytest.fixture
def mcp(home, monkeypatch):
    """call(tool, arguments, answer) -> (result, requests); list() -> tools; instructions() -> text."""
    requests = []

    def use(answer):
        def handler(request):
            requests.append(request)
            return answer(request)
        monkeypatch.setattr(server, "TRANSPORT", httpx.MockTransport(handler))
        server.SERVICES.clear()

    async def session(work):
        async with Client(server.SERVER, client_info=Implementation(name="Claude Code", version="2.1.281")) as client:
            return await work(client)

    class Session:
        requests_seen = requests

        @staticmethod
        def call(tool, arguments, answer=lambda request: envelope()):
            use(answer)
            requests.clear()
            result = anyio.run(session, lambda client: client.call_tool(tool, arguments))
            return result, list(requests)

        @staticmethod
        def tools():
            return anyio.run(session, lambda client: client.list_tools()).tools

        @staticmethod
        def instructions():
            async def work(client):
                return client.instructions
            return anyio.run(session, work)
    return Session
