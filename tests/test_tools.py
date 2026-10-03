"""Five tools, compact schemas, the service's text back, and nothing of the person's or the token's ever shown."""

import json
import re
from pathlib import Path

import httpx
import pytest

from conftest import TOKEN, URL, envelope
from wirk_mcp import server

NAMES = ["wirk_status", "wirk_query", "wirk_write", "wirk_review", "wirk_show"]


def definitions(tools):
    return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in tools]


def test_exactly_five_compact_tools(mcp):
    tools = definitions(mcp.tools())
    assert [t["name"] for t in tools] == NAMES
    assert len(json.dumps(tools, separators=(",", ":"), ensure_ascii=False).encode()) <= 5120
    assert len(mcp.instructions().encode()) <= 900
    assert "$defs" not in json.dumps(tools)

    def walk(node):
        if isinstance(node, dict):
            if "enum" in node:
                assert node.get("type") == "string"
            assert not ("type" in node and "title" in node), node  # no generated schema titles
            assert not isinstance(node.get("additionalProperties"), dict)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(tools)
    assert all(t["inputSchema"]["additionalProperties"] is False for t in tools)


def test_agent_text_names_only_the_persons_decision(mcp):
    text = json.dumps(definitions(mcp.tools())) + mcp.instructions()
    assert re.findall(r"wirk \w+[^\"]*?--person", text) == ["wirk review ID@N accept --reason WHY --person"] * 2
    assert "admin" not in text and "person-token" not in text
    assert not re.search(r"\bsteward(?!_id)", text)


def test_agent_text_says_who_decides_what_is_live_and_what_refusals_mean(mcp):
    tools = {t["name"]: t["description"] for t in definitions(mcp.tools())}
    assert "Only people decide proposals" in mcp.instructions()
    assert "person_required" in tools["wirk_review"] and "--person" in tools["wirk_review"]
    assert "not_authorized for your own" in tools["wirk_review"]
    assert tools["wirk_show"].startswith("Not live yet") and "views_unavailable" in tools["wirk_show"]
    assert "when you may make" in tools["wirk_write"] and "requires_review" in tools["wirk_write"]
    assert "basis_changed" in tools["wirk_write"]
    assert "quotation_mismatch" in json.dumps(definitions(mcp.tools()))


@pytest.mark.parametrize("tool, route", [("wirk_status", "/v2/status"), ("wirk_query", "/v2/query"),
                                         ("wirk_write", "/v2/write"), ("wirk_review", "/v2/review"),
                                         ("wirk_show", "/v2/show")])
def test_each_tool_posts_its_body_and_returns_the_text(mcp, tool, route):
    arguments = {"wirk_write": {"operations": [{"op": "item.create", "data": {"title": "T"}}]},
                 "wirk_review": {"decisions": [{"id": "c4a1e902", "revision": 1, "action": "accept", "reason": "Fine"}]},
                 "wirk_show": {"preset": "status"}}.get(tool, {})
    result, requests = mcp.call(tool, arguments, lambda r: envelope("the service's text"))
    assert [r.url.path for r in requests] == [route] and requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    body = json.loads(requests[0].content)
    assert body["format"] == "text"
    if tool == "wirk_write":
        assert re.fullmatch(r"w-[0-9a-f]{10}", body["request_id"])
    if tool == "wirk_review":
        assert re.fullmatch(r"r-[0-9a-f]{10}", body["request_id"])
    assert [c.text for c in result.content] == ["the service's text"]
    assert result.structured_content is None and result.is_error is False


def test_a_refusal_is_an_error_with_the_services_words(mcp):
    result, requests = mcp.call("wirk_query", {"fetch": ["nope"]}, lambda r: envelope(
        "Error no_match: no readable item is titled \"nope\"", ok=False,
        errors=[{"code": "no_match", "message": "x"}], status=422))
    assert result.is_error is True and result.content[0].text.startswith("Error no_match")


def test_fetch_id_at_revision_becomes_a_revision_ref(mcp):
    result, requests = mcp.call("wirk_query", {"fetch": ["5c1e7a90@2", "Meet@3", "6a0d2e83"]})
    assert json.loads(requests[0].content)["fetch"] == [{"ref": "5c1e7a90", "revision": 2}, "Meet@3", "6a0d2e83"]


def test_json_format_returns_the_envelope(mcp):
    result, requests = mcp.call("wirk_query", {"fields": {"status": "open"}, "format": "json"},
                                lambda r: envelope(data={"cards": [], "total": 0}))
    assert json.loads(result.content[0].text)["data"] == {"cards": [], "total": 0}


def test_status_reports_the_host_and_a_session(mcp):
    result, requests = mcp.call("wirk_status", {"task": "fix it"})
    header = requests[0].headers["wirk-context"]
    assert header.startswith("harness=claude-code version=2.1.281 session=")
    assert re.search(r"session=[0-9a-f]{16}\b", header)
    result, requests = mcp.call("wirk_query", {})
    assert "wirk-context" not in requests[0].headers


def test_show_adds_the_timezone_and_is_never_resent(mcp, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    result, requests = mcp.call("wirk_show", {"preset": "status"})
    assert json.loads(requests[0].content)["timezone"] == "Europe/London"

    def slow(request):
        raise httpx.ReadTimeout("slow")
    result, requests = mcp.call("wirk_show", {"preset": "status"}, slow)
    assert result.is_error and len(requests) == 1


def test_a_write_is_resent_once_and_an_unknown_outcome_names_the_retry(mcp):
    def slow(request):
        raise httpx.ReadTimeout("slow")
    result, requests = mcp.call("wirk_write", {"request_id": "w-7", "operations": [{"op": "item.create", "data": {}}]}, slow)
    assert len(requests) == 2 and requests[0].content == requests[1].content
    assert result.is_error and "outcome_unknown" in result.content[0].text and "w-7" in result.content[0].text


def test_client_failures_name_the_url_and_never_the_token(mcp, home):
    def refused(request):
        raise httpx.ConnectError("refused")
    result, requests = mcp.call("wirk_status", {}, refused)
    assert result.is_error and URL in result.content[0].text and TOKEN not in result.content[0].text
    (home / "agent-token").unlink()
    result, requests = mcp.call("wirk_status", {})
    assert result.is_error and "wirk login" in result.content[0].text and requests == []


def test_the_person_token_is_never_opened(mcp, home, monkeypatch):
    (home / "person-token").write_text("wirk_" + "b" * 43)
    (home / "person-token").chmod(0o600)
    opened = []
    from wirk_cli import cli
    real = cli.read_token
    monkeypatch.setattr(cli, "read_token", lambda path: opened.append(path.name) or real(path))
    for tool in NAMES:
        mcp.call(tool, {"wirk_write": {"operations": []}, "wirk_review": {"decisions": []}}.get(tool, {}))
    assert set(opened) == {"agent-token"}


def test_one_client_is_kept_while_the_configuration_holds(home):
    first, second = server.service(), server.service()
    assert first is second
    (home / "agent-token").write_text("wirk_" + "c" * 43)
    assert server.service() is not first


ROOT = Path(__file__).parent.parent
PRIVATE = ["/Us" "ers/", r"\b(?:wsp|item|change|proposal|link|acc)_[0-9a-f]{32}\b", "Co-Auth" "ored-By",
           "Cla" "ude(?! Code)", "Anthr" "opic", r"\bOpus\b", r"\bSonnet\b", r"\bFable\b",
           r"[A-Za-z0-9._%+-]+@(?![A-Za-z0-9.-]*(?:example\.|wirk\.life))[A-Za-z0-9.-]+\.[a-z]{2,}"]
WORDING = [r"\bworkspace\b(?!_id)", r"\bwork item", r"kind=wirk", r"· wirk ·", r"\bsteward(?!_id)"]


def test_privacy_wording_and_no_v1():
    import subprocess
    names = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    for name in names:
        if (ROOT / name).is_file() and name != "LICENSE":
            text = (ROOT / name).read_text(errors="replace")
            for pattern in PRIVATE:
                assert not re.search(pattern, text), (name, pattern)
            if name.endswith((".md", ".json")) or name.startswith("src/"):
                assert "/v1/" not in text, name
    agent_text = (ROOT / "README.md").read_text() + (ROOT / "src/wirk_mcp/tools.json").read_text()
    for pattern in WORDING:
        assert not re.search(pattern, agent_text), pattern


def test_the_package_pins_the_tested_cli():
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "wirk==0.3.1" in project["dependencies"] and not any("git+" in d for d in project["dependencies"])


def test_an_unknown_outcome_is_worded_for_mcp(mcp):
    def slow(request):
        raise httpx.ReadTimeout("slow")
    result, requests = mcp.call("wirk_write", {"request_id": "w-7", "operations": [{"op": "item.create", "data": {}}]}, slow)
    text = result.content[0].text
    assert "request_id w-7" in text and "wirk_query" in text and "--request-id" not in text and "wirk query" not in text


def test_the_server_reuses_the_clis_connection_and_ids():
    import inspect
    source = inspect.getsource(server)
    assert "connect(" in source and "new_id(" in source and "read_token" not in source and "token_hex(5)" not in source
