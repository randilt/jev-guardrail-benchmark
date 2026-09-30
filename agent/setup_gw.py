"""Deploy (or delete) the agent benchmark's gateway routes through the management API.

  adojo-llm-baseline         LLM proxy on the Azure OpenAI provider, no policies
  adojo-llm-full             the same, with typesafe-jev-content-safety
  adojo-<suite>-baseline     MCP proxy to the harness MCP server, no policies
  adojo-<suite>-full         the same, with intent verification (the suite's scope) and result screening

Every policy runs at its shipped defaults; intent verification gets one "*" rule with the suite's scope.

  python -m agent.setup_gw up [baseline|full]
  python -m agent.setup_gw down
"""
import json
import sys

import requests
import yaml

from agent import config as A
from bench import config as C

AUTH = (C.GATEWAY_MGMT_USER, C.GATEWAY_MGMT_PASSWORD)
MGMT = C.GATEWAY_MGMT_URL
INTENT_POLICY = C.get("AGENT_INTENT_POLICY", "typesafe-jev-mcp-tool-guardrail")  # local name of intent verification
RESULT_POLICY = "typesafe-jev-mcp-tool-result-screening"


def llm_policies(config):
    if config == "baseline":
        return []
    # Tool filtering (PR #313) was left out after the pilot: at its defaults it keeps 5 tools per request and
    # re-filters every turn on the first user message, so multi-step tasks lose tools they need (see README).
    return [
        {"name": "typesafe-jev-content-safety", "version": "v0", "params": {"request": {"showAssessment": False}}},
    ]


def mcp_policies(config, suite, scopes):
    if config == "baseline":
        return []
    return [
        {"name": INTENT_POLICY, "version": "v0", "params": {"tools": [{"name": "*", "scope": scopes[suite]}]}},
        {"name": RESULT_POLICY, "version": "v0", "params": {"tools": [{"name": "*"}]}},
    ]


def put(kind_path, name, body):
    requests.delete(f"{MGMT}/{kind_path}/{name}", auth=AUTH, timeout=30)
    r = requests.post(f"{MGMT}/{kind_path}", auth=AUTH, data=json.dumps(body),
                      headers={"Content-Type": "application/yaml"}, timeout=30)
    print(f"deploy {name}: HTTP {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
    return r.status_code < 300


def up(configs):
    scopes = yaml.safe_load(open(A.SCOPES_FILE))
    ok = True
    for config in configs:
        name = A.llm_route(config)
        ok &= put("llm-proxies", name, {
            "apiVersion": "gateway.api-platform.wso2.com/v1", "kind": "LlmProxy", "metadata": {"name": name},
            "spec": {"displayName": name, "version": "v1.0", "context": f"/{name}",
                     "provider": {"id": A.PROVIDER_ID, "auth": {"type": "api-key", "header": A.PROVIDER_KEY_HEADER,
                                                                "value": A.provider_key()}},
                     "globalPolicies": llm_policies(config)}})
        for suite in A.SUITES:
            name = A.mcp_route(suite, config)
            spec = {"displayName": name, "version": "v1.0", "context": f"/{name}",
                    "upstream": {"url": f"http://{A.MCP_HOST_FROM_GATEWAY}:{A.MCP_PORT}/mcp/{suite}"}}
            policies = mcp_policies(config, suite, scopes)
            if policies:
                spec["policies"] = policies
            ok &= put("mcp-proxies", name, {"apiVersion": "gateway.api-platform.wso2.com/v1", "kind": "Mcp",
                                            "metadata": {"name": name}, "spec": spec})
    return ok


def down():
    for config in A.CONFIGS:
        r = requests.delete(f"{MGMT}/llm-proxies/{A.llm_route(config)}", auth=AUTH, timeout=30)
        print(f"delete {A.llm_route(config)}: HTTP {r.status_code}")
        for suite in A.SUITES:
            r = requests.delete(f"{MGMT}/mcp-proxies/{A.mcp_route(suite, config)}", auth=AUTH, timeout=30)
            print(f"delete {A.mcp_route(suite, config)}: HTTP {r.status_code}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["down"]:
        down()
    elif sys.argv[1:2] == ["up"]:
        sys.exit(0 if up(sys.argv[2:] or list(A.CONFIGS)) else 1)
    else:
        print(__doc__)
