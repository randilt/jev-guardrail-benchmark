"""Settings for the agent-workflow benchmark, read from the repo's .env or the environment.

Gateway settings and the LLM provider key are shared with the content-safety benchmark (bench/config.py).
"""
import os

from bench import config as C

ROOT = C.ROOT
AGENT_DIR = os.path.join(ROOT, "agent")
DATA_DIR = os.path.join(AGENT_DIR, "data")
SAMPLE_FILE = os.path.join(DATA_DIR, "sample_v1.json")
SCOPES_FILE = os.path.join(AGENT_DIR, "scopes.yaml")
RESULTS_DIR = C.get("AGENT_RESULTS_DIR", os.path.join(AGENT_DIR, "results"))

BENCHMARK_VERSION = C.get("AGENT_BENCHMARK_VERSION", "v1.2.2")
SUITES = ["workspace", "travel", "banking", "slack"]
ATTACK = "important_instructions"

# LLM: a gateway LLM proxy on an Azure OpenAI provider (OpenAI-compatible chat completions with tools).
PROVIDER_ID = C.get("AGENT_PROVIDER_ID", "gpt-4o-mini-azure-open-ai")
provider_key = lambda: C.get("AGENT_PROVIDER_KEY") or C.judge_key()  # the provider route's api-key-auth key
PROVIDER_KEY_HEADER = C.get("AGENT_PROVIDER_KEY_HEADER", "X-API-Key")
MODEL = C.get("AGENT_MODEL", "gpt-4o-mini")
# AgentDojo's important_instructions attack reads the model name from the pipeline name.
MODEL_ID = C.get("AGENT_MODEL_ID", "gpt-4o-mini-2024-07-18")
API_VERSION = C.get("AGENT_API_VERSION", "2024-10-21")
# AgentDojo's request helper sends `temperature or NOT_GIVEN`, so 0 is never sent and the model runs at its
# default temperature. This benchmark sends the temperature explicitly (0 unless set), to keep runs repeatable.
TEMPERATURE = float(C.get("AGENT_TEMPERATURE", "0"))
# The name AgentDojo's important_instructions attack uses for the model ("... to you, GPT-4 ...").
MODEL_DISPLAY_NAME = C.get("AGENT_MODEL_DISPLAY_NAME", "GPT-4")
# AgentDojo sends the system prompt as role "developer"; set to true if the deployment rejects it.
MAP_DEVELOPER_TO_SYSTEM = C.get("AGENT_MAP_DEVELOPER_TO_SYSTEM", "false").lower() == "true"

# Tools: the harness runs an MCP server; the gateway's MCP proxies forward to it.
MCP_BIND = C.get("AGENT_MCP_BIND", "127.0.0.1")
MCP_PORT = int(C.get("AGENT_MCP_PORT", "18780"))
MCP_HOST_FROM_GATEWAY = C.get("AGENT_MCP_HOST_FROM_GATEWAY", "host.docker.internal")
GATEWAY_URL = C.GATEWAY_URL
GATEWAY_MCP_URL = C.get("GATEWAY_MCP_URL", "http://localhost:8080").rstrip("/")
GATEWAY_TLS_VERIFY = C.GATEWAY_TLS_VERIFY

# Prices for the cost table (check the pricing pages before publishing).
# Defaults are gpt-4o list prices (per million tokens); check your Azure deployment's price before publishing.
PRICE_LLM_INPUT_PER_M = float(C.get("PRICE_AGENT_INPUT_PER_M", "2.50"))
PRICE_LLM_OUTPUT_PER_M = float(C.get("PRICE_AGENT_OUTPUT_PER_M", "10.00"))

CONFIGS = ("baseline", "full")


def llm_route(config):
    return f"adojo-llm-{config}"


def mcp_route(suite, config):
    return f"adojo-{suite}-{config}"
