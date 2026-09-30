"""An MCP server (Streamable HTTP, JSON responses) that runs AgentDojo tools inside the harness process.

The gateway's MCP proxies forward to it, so every tool call and its result pass through the gateway.
Each MCP session is bound to one running task's AgentDojo environment object, so tools mutate the same
environment AgentDojo later scores. The executor binds a session to its task before calling tools.
"""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str

PROTOCOL_VERSION = "2025-06-18"


class Registry:
    """Session id -> (FunctionsRuntime, environment) for the task that owns the session."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def open(self):
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = None
        return sid

    def bind(self, sid, runtime, env):
        with self._lock:
            self._sessions[sid] = (runtime, env)

    def get(self, sid):
        with self._lock:
            return self._sessions.get(sid)

    def close(self, sid):
        with self._lock:
            self._sessions.pop(sid, None)


REGISTRY = Registry()


def tool_list(runtime):
    return [{"name": f.name, "description": f.description, "inputSchema": f.parameters.model_json_schema()}
            for f in runtime.functions.values()]


def call_tool(runtime, env, name, arguments):
    """Runs the tool the same way AgentDojo's ToolsExecutor does, and returns an MCP tool result.
    A tool error becomes a result marked isError with AgentDojo's error text."""
    result, error = runtime.run_function(env, name, arguments or {})
    if error is not None:
        return {"content": [{"type": "text", "text": error}], "isError": True}
    return {"content": [{"type": "text", "text": tool_result_to_str(result)}]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, obj=None, session=None):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(405, {"error": "SSE stream not supported"})

    def do_DELETE(self):
        sid = self.headers.get("Mcp-Session-Id")
        if sid:
            REGISTRY.close(sid)
        self._send(200)

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        rid, method = req.get("id"), req.get("method")
        if rid is None:  # a notification
            return self._send(202)
        if method == "initialize":
            sid = REGISTRY.open()
            return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentdojo-mcp", "version": "1"}}}, session=sid)
        bound = REGISTRY.get(self.headers.get("Mcp-Session-Id", ""))
        if bound is None:
            return self._send(404, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": "Unknown or unbound session"}})
        runtime, env = bound
        if method == "tools/list":
            return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list(runtime)}})
        if method == "tools/call":
            params = req.get("params") or {}
            result = call_tool(runtime, env, params.get("name"), params.get("arguments"))
            return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": result})
        return self._send(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})


def serve(bind, port):
    """Starts the server on a daemon thread and returns it."""
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
