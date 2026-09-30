"""AgentDojo pipeline elements that send every LLM call and every tool call through the gateway."""
import json
import random
import threading
import time
from ast import literal_eval
from collections.abc import Sequence

import httpx
import openai
import requests
from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.errors import AbortAgentError
from agentdojo.agent_pipeline.llms.google_llm import EMPTY_FUNCTION_NAME
from agentdojo.agent_pipeline.llms.openai_llm import (OpenAILLM, _function_to_openai, _message_to_openai,
                                                      _openai_to_assistant_message)
from agentdojo.models import MODEL_NAMES
from openai import NOT_GIVEN
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_random_exponential
from agentdojo.agent_pipeline.tool_execution import is_string_list
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.types import ChatMessage, ChatToolResultMessage, text_content_block_from_string

from agent import config as A
from agent.mcp_server import REGISTRY

# Texts the gateway policies return, used to tell an intervention from an ordinary tool error.
RESULT_WITHHELD = "The gateway withheld this tool result because it appears to contain instructions aimed at the AI assistant."
RESULT_UNCHECKED = "The gateway withheld this tool result because it could not be checked."
INTENT_BLOCKED = "MCP tool call blocked by guardrail"
INTENT_UNCHECKED = "MCP tool call could not be checked by guardrail"
LLM_BLOCKED_TEXT = "The gateway blocked this request."

_local = threading.local()


class TaskContext:
    """What happened in one task run: set on the worker thread before the task starts."""

    def __init__(self, suite, config, mcp_session):
        self.suite, self.config, self.mcp_session = suite, config, mcp_session
        self.llm_calls = self.prompt_tokens = self.completion_tokens = 0
        self.llm_seconds = self.tool_seconds = 0.0
        self.tool_calls = 0
        self.interventions = []  # {"layer", "tool", "turn"}

    def add(self, layer, tool=None):
        self.interventions.append({"layer": layer, "tool": tool, "turn": self.llm_calls})


def set_context(ctx):
    _local.ctx = ctx


def context():
    return getattr(_local, "ctx", None)


RATE_LIMIT_ATTEMPTS = 10


@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(3), reraise=True,
       retry=retry_if_not_exception_type((openai.BadRequestError, openai.UnprocessableEntityError)))
def _create(client, model, messages, tools, temperature):
    return client.chat.completions.create(model=model, messages=messages, tools=tools or NOT_GIVEN,
                                          tool_choice="auto" if tools else NOT_GIVEN, temperature=temperature)


def chat_completion_request(client, model, messages, tools, temperature):
    """AgentDojo's chat_completion_request (same retries, tools and tool_choice), with two changes: the
    temperature is sent even when it is 0, and an HTTP 429 (the deployment's token rate limit) waits for
    Azure's Retry-After and tries again, up to RATE_LIMIT_ATTEMPTS times. Retries don't change what the
    agent sees; they only keep a rate limit from failing the task."""
    for attempt in range(RATE_LIMIT_ATTEMPTS):
        try:
            return _create(client, model, messages, tools, temperature)
        except openai.RateLimitError as e:
            if attempt == RATE_LIMIT_ATTEMPTS - 1:
                raise
            retry_after = e.response.headers.get("retry-after") if e.response is not None else None
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                wait = min(60.0, 2.0 ** attempt)
            time.sleep(wait + random.uniform(0, 2))


class GatewayLLM(OpenAILLM):
    """AgentDojo's OpenAILLM, pointed at a gateway LLM proxy. It records token usage, and a request the
    gateway blocks (content safety, HTTP 422) or Azure's content filter refuses ends the task cleanly
    (AbortAgentError), so it is scored instead of crashing the run."""

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = [], extra_args: dict = {}):
        ctx = context()
        openai_messages = [_message_to_openai(m, self.model) for m in messages]
        if A.MAP_DEVELOPER_TO_SYSTEM:
            openai_messages = [dict(m, role="system") if m.get("role") == "developer" else m for m in openai_messages]
        openai_tools = [_function_to_openai(t) for t in runtime.functions.values()]
        t = time.perf_counter()
        try:
            completion = chat_completion_request(self.client, self.model, openai_messages, openai_tools, A.TEMPERATURE)
        except openai.UnprocessableEntityError as e:
            if ctx:
                ctx.add("content_safety_blocked")
            raise AbortAgentError(LLM_BLOCKED_TEXT, list(messages), env) from e
        except openai.BadRequestError as e:
            if "content_filter" in repr(e) or "content management policy" in repr(e):
                if ctx:
                    ctx.add("azure_content_filter")
                raise AbortAgentError(LLM_BLOCKED_TEXT, list(messages), env) from e
            raise
        finally:
            if ctx:
                ctx.llm_seconds += time.perf_counter() - t
        if ctx:
            ctx.llm_calls += 1
            if completion.usage:
                ctx.prompt_tokens += completion.usage.prompt_tokens or 0
                ctx.completion_tokens += completion.usage.completion_tokens or 0
        output = _openai_to_assistant_message(completion.choices[0].message)
        return query, runtime, env, [*messages, output], extra_args


def mcp_post(url, session, body):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    r = requests.post(url, data=json.dumps(body), headers=headers, timeout=120)
    return r


def parse_mcp(r, rid):
    """The JSON-RPC message answering rid, from a JSON or event-stream response."""
    if "text/event-stream" in r.headers.get("content-type", ""):
        for block in r.text.split("\n\n"):
            data = "\n".join(l[5:].lstrip(" ") for l in block.split("\n") if l.startswith("data:"))
            try:
                m = json.loads(data)
            except ValueError:
                continue
            if m.get("id") == rid:
                return m
        return None
    try:
        return r.json()
    except ValueError:
        return None


def open_session(url):
    """initialize through the gateway; returns the MCP session id."""
    r = mcp_post(url, None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "agentdojo-gw", "version": "1"}}})
    r.raise_for_status()
    sid = r.headers.get("Mcp-Session-Id")
    if not sid:
        raise RuntimeError(f"no Mcp-Session-Id from {url}")
    mcp_post(url, sid, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return sid


class McpToolsExecutor(BasePipelineElement):
    """Drop-in for AgentDojo's ToolsExecutor that runs each tool call as an MCP tools/call through the
    suite's gateway MCP proxy. It keeps ToolsExecutor's checks and argument handling. The harness MCP server
    runs the tool on this task's environment. A result marked isError, or a JSON-RPC error, is given to the
    model the way AgentDojo gives it a tool error: as the tool message's text."""

    def __init__(self, mcp_url):
        self.mcp_url = mcp_url
        self._next_id = 1000
        self._lock = threading.Lock()

    def _id(self):
        with self._lock:
            self._next_id += 1
            return self._next_id

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = [], extra_args: dict = {}):
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return query, runtime, env, messages, extra_args
        ctx = context()
        REGISTRY.bind(ctx.mcp_session, runtime, env)
        results = []
        for tool_call in messages[-1]["tool_calls"]:
            def result(text, error=None):
                return ChatToolResultMessage(role="tool", content=[text_content_block_from_string(text)],
                                             tool_call_id=tool_call.id, tool_call=tool_call, error=error)
            if tool_call.function == EMPTY_FUNCTION_NAME:
                results.append(result("", "Empty function name provided. Provide a valid function name."))
                continue
            if tool_call.function not in (t.name for t in runtime.functions.values()):
                results.append(result("", f"Invalid tool {tool_call.function} provided."))
                continue
            for k, v in tool_call.args.items():
                if isinstance(v, str) and is_string_list(v):
                    tool_call.args[k] = literal_eval(v)

            rid = self._id()
            t = time.perf_counter()
            r = mcp_post(self.mcp_url, ctx.mcp_session, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                                                         "params": {"name": tool_call.function, "arguments": dict(tool_call.args)}})
            ctx.tool_seconds += time.perf_counter() - t
            ctx.tool_calls += 1
            m = parse_mcp(r, rid)
            if m is None:
                raise RuntimeError(f"unreadable MCP response (HTTP {r.status_code}) for {tool_call.function}: {r.text[:200]}")
            if "error" in m:
                message = (m["error"] or {}).get("message", "")
                if message == INTENT_BLOCKED:
                    ctx.add("intent_blocked", tool_call.function)
                elif message == INTENT_UNCHECKED:
                    ctx.add("intent_unchecked", tool_call.function)
                results.append(result("", message or "Tool call failed."))
                continue
            res = m.get("result") or {}
            text = "\n".join(c.get("text", "") for c in res.get("content") or [] if c.get("type") == "text")
            if res.get("isError"):
                if text == RESULT_WITHHELD:
                    ctx.add("result_withheld", tool_call.function)
                elif text == RESULT_UNCHECKED:
                    ctx.add("result_unchecked", tool_call.function)
                results.append(result("", text))
            else:
                results.append(result(text))
        return query, runtime, env, [*messages, *results], extra_args


def build_pipeline(config, suite):
    """The same pipeline shape AgentDojo builds with no defense, with the LLM and tools behind the gateway."""
    client = openai.OpenAI(
        base_url=f"{A.GATEWAY_URL}/{A.llm_route(config)}",
        api_key="unused",  # the gateway proxy authenticates to the provider
        default_query={"api-version": A.API_VERSION},
        http_client=httpx.Client(verify=A.GATEWAY_TLS_VERIFY, timeout=120),
        max_retries=0,
    )
    MODEL_NAMES.setdefault(A.MODEL_ID, A.MODEL_DISPLAY_NAME)  # lets the attack name the model in its text
    llm = GatewayLLM(client, A.MODEL)
    executor = McpToolsExecutor(f"{A.GATEWAY_MCP_URL}/{A.mcp_route(suite, config)}/mcp")
    pipeline = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), llm, ToolsExecutionLoop([executor, llm])])
    pipeline.name = f"{A.MODEL_ID}-gw-{config}"
    pipeline.mcp_url = executor.mcp_url
    return pipeline
