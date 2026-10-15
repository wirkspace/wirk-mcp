"""Five tools over the WIRK service: the arguments are the v2 request bodies, except that a write's uploads and
attach_uploads may name local files, which are stored first; the answer is the service's text.

The HTTP client, configuration, token checks and the ID@N rule come from wirk-cli, so each exists once. Only the
agent token is read; the person's own token is never opened here.
"""

import copy
import json
import os
import re
import secrets
import threading
from pathlib import Path

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from wirk_cli import context, grammar
from wirk_cli.cli import connect, local_zone, new_id, problem_text, readable, store
from wirk_cli.client import Failure, Service
from wirk_cli.grammar import UsageError

from . import __version__

DEFINITIONS = json.loads((Path(__file__).parent / "tools.json").read_text())
ROUTES = {"wirk_status": "/v2/status", "wirk_query": "/v2/query", "wirk_write": "/v2/write",
          "wirk_review": "/v2/review", "wirk_show": "/v2/show"}
UPLOAD_ID = re.compile(r"(upload_)?[0-9a-f]{6,32}")  # core's form; any other string in a file key is a local path
FILE_KEYS = {"item.create": ("data", "uploads"), "message.send": ("data", "uploads"),
             "item.edit": ("patch", "attach_uploads")}
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


class Cancelled(Exception):
    """The host gave up on the call."""


class Watched:
    """An open file whose reads stop once the call is cancelled, so no more bytes leave."""

    def __init__(self, source, cancelled: threading.Event):
        self.source, self.cancelled = source, cancelled

    def read(self, size: int = -1) -> bytes:
        if self.cancelled.is_set():
            raise Cancelled
        return self.source.read(size)

    def seek(self, *where):
        return self.source.seek(*where)


def store_files(body: dict, cancelled: threading.Event) -> str | None:
    """Store each local path in the write's file keys and put its upload ID in its place. A returned text means stop:
    nothing is written."""
    request_id, found = body["request_id"], []
    for index, operation in enumerate(body.get("operations") or []):
        part, key = FILE_KEYS.get(operation.get("op") if isinstance(operation, dict) else None, (None, None))
        entries = (operation.get(part) or {}).get(key) if part else None
        if isinstance(entries, list):
            found += [(entries, n, os.path.expanduser(entry), f"{request_id}/{index}/{n}") for n, entry in enumerate(entries)
                      if isinstance(entry, str) and not UPLOAD_ID.fullmatch(entry)]
    for _, _, path, confirm_id in found:  # every check before any request
        if not os.path.isabs(path):
            return f"{path} is neither an upload ID nor an absolute path to a file on this machine. Nothing was sent."
        if len(confirm_id) > 200:
            return (f"request_id is too long: with {confirm_id[len(request_id):]} added it names an upload, and that "
                    "must stay within 200 characters. Nothing was sent.")
        try:
            with readable(path):
                pass
        except UsageError as error:
            return f"{error}. Nothing was sent."
    stored = []
    for entries, n, path, confirm_id in found:
        try:
            with readable(path) as source:
                answer = store(Watched(source, cancelled), path, confirm_id, "", service(),
                               workspace_id=body.get("workspace_id"))
        except Failure as failure:  # storage or an unknown outcome, in the client's words without its CLI hint
            answer = {"ok": False, "errors": [{"code": failure.code, "message": str(failure)}]}
        except Cancelled:
            break
        if not answer["ok"]:
            retry = (f"A file or path changed since request_id {request_id} was first used: send these arguments under a "
                     "new request_id." if answer["errors"][0]["code"] == "request_conflict" else
                     f"Resend the identical arguments with request_id {request_id} to retry; stored files are reused, and "
                     "changed arguments need a new request_id.")
            return "\n".join([f"{Path(path).name}: {problem_text(answer)}",
                              *([f"Stored but attached to nothing: {', '.join(stored)}."] if stored else []),
                              f"Nothing was written. {retry}"])
        entries[n] = answer["data"]["upload"]["id"]
        stored.append(Path(path).name)
    return "Cancelled; nothing was written." if cancelled.is_set() else None


def call(name: str, arguments: dict, client: types.Implementation | None, cancelled: threading.Event) -> tuple[str, bool]:
    body = copy.deepcopy(arguments)
    if name == "wirk_query" and body.get("fetch"):
        body["fetch"] = [grammar.ref(ref) if isinstance(ref, str) else ref for ref in body["fetch"]]
    if name in ("wirk_write", "wirk_review"):
        body.setdefault("request_id", new_id(name[5]))
    if name == "wirk_show" and "revoke" not in body and local_zone():
        body.setdefault("timezone", local_zone())
    body.setdefault("format", "text")
    if name == "wirk_write" and (stopped := store_files(body, cancelled)):
        return stopped, True
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
    if "notifications" in answer:  # messages for you come last, as text ends with them
        answer["notifications"] = answer.pop("notifications")
    text = json.dumps(answer, ensure_ascii=False) if body["format"] == "json" else answer.get("text") or problem_text(answer)
    return text, not answer["ok"]


async def list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[types.Tool(name=tool["name"], description=tool["description"],
                                                   input_schema=tool["inputSchema"]) for tool in DEFINITIONS["tools"]])


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name not in ROUTES:
        return types.CallToolResult(content=[types.TextContent(text=f"Unknown tool {params.name}")], is_error=True)
    client = ctx.session.client_params.client_info if ctx.session.client_params else None
    cancelled = threading.Event()  # a host that gives up cancels this call; the thread then never writes
    try:
        text, failed = await anyio.to_thread.run_sync(call, params.name, params.arguments or {}, client, cancelled,
                                                      abandon_on_cancel=True)
    except anyio.get_cancelled_exc_class():
        cancelled.set()
        raise
    return types.CallToolResult(content=[types.TextContent(text=text)], is_error=failed)


SERVER = Server("WIRK", version=__version__, instructions=DEFINITIONS["instructions"], on_list_tools=list_tools,
                on_call_tool=call_tool)


def main() -> None:
    async def run():
        async with stdio_server() as (read, write):
            await SERVER.run(read, write, SERVER.create_initialization_options())
    anyio.run(run)
