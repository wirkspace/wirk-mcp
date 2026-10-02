"""Five tools over the WIRK service: the arguments are the v2 request bodies, the answer is the service's text.

The HTTP client, configuration, token checks and the ID@N rule come from wirk-cli, so each exists once. Only the
agent token is read; the person's own token is never opened here.
"""

import json
import secrets
from pathlib import Path

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from wirk_cli import context, grammar
from wirk_cli.cli import connect, local_zone, new_id, problem_text
from wirk_cli.client import Failure, Service

from . import __version__

DEFINITIONS = json.loads((Path(__file__).parent / "tools.json").read_text())
ROUTES = {"wirk_status": "/v2/status", "wirk_query": "/v2/query", "wirk_write": "/v2/write",
          "wirk_review": "/v2/review", "wirk_show": "/v2/show"}
SESSION = secrets.token_hex(8)  # one per server process, reported with status
TRANSPORT = None  # tests put a fake service here
SERVICES: list = []


def service() -> Service:
    """The CLI's connection with the agent token, kept while the configuration holds so its connections are reused;
    a new login needs no restart."""
    fresh = connect(TRANSPORT)
    if not (SERVICES and SERVICES[0].same(fresh)):
        SERVICES[:] = [fresh]
    return SERVICES[0]


def call(name: str, arguments: dict, client: types.Implementation | None) -> tuple[str, bool]:
    body = dict(arguments)
    if name == "wirk_query" and body.get("fetch"):
        body["fetch"] = [grammar.ref(ref) if isinstance(ref, str) else ref for ref in body["fetch"]]
    if name in ("wirk_write", "wirk_review"):
        body.setdefault("request_id", new_id(name[5]))
    if name == "wirk_show" and "revoke" not in body and local_zone():
        body.setdefault("timezone", local_zone())
    body.setdefault("format", "text")
    headers = {"Wirk-Context": context.header(client.name if client else "", client.version if client else "", SESSION)} \
        if name == "wirk_status" else None
    try:
        answer = service().post(ROUTES[name], body, uncertain=body.get("request_id"), resend=name != "wirk_show",
                                headers=headers)
    except Failure as failure:
        if failure.code == "outcome_unknown":  # the retry in MCP's terms: the same arguments, the same request_id
            failure.hint = (f"Resend the identical arguments with request_id {body['request_id']}: it applies once or "
                            f"returns the stored receipt. Or call wirk_query with receipt {body['request_id']}.")
        return failure.text(), True
    text = json.dumps(answer, ensure_ascii=False) if body["format"] == "json" else answer.get("text") or problem_text(answer)
    return text, not answer["ok"]


async def list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[types.Tool(name=tool["name"], description=tool["description"],
                                                   input_schema=tool["inputSchema"]) for tool in DEFINITIONS["tools"]])


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name not in ROUTES:
        return types.CallToolResult(content=[types.TextContent(text=f"Unknown tool {params.name}")], is_error=True)
    client = ctx.session.client_params.client_info if ctx.session.client_params else None
    text, failed = await anyio.to_thread.run_sync(call, params.name, params.arguments or {}, client)
    return types.CallToolResult(content=[types.TextContent(text=text)], is_error=failed)


SERVER = Server("WIRK", version=__version__, instructions=DEFINITIONS["instructions"], on_list_tools=list_tools,
                on_call_tool=call_tool)


def main() -> None:
    async def run():
        async with stdio_server() as (read, write):
            await SERVER.run(read, write, SERVER.create_initialization_options())
    anyio.run(run)
