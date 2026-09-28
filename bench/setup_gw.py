"""Deploy (or delete) the benchmark routes on a WSO2 AI Gateway, through its management API.

  bench-none   no guardrail (the baseline for added latency)
  bench-jev    typesafe-jev-content-safety, request side, shipped defaults
  bench-azure  azure-content-safety-content-moderation, request side, shipped defaults

All three send to the mock upstream (mock_upstream/mock.py), so only the guardrail's own time is measured.

  python -m bench.setup_gw up [route ...]
  python -m bench.setup_gw down
"""
import json, sys, time

import requests

from bench import config as C
from bench.systems import gateway

ROUTES = {
    "bench-none": [],
    "bench-jev": [{"name": "typesafe-jev-content-safety", "version": C.JEV_POLICY_VERSION,
                   "params": {"request": {"showAssessment": True}}}],
    "bench-azure": [{"name": "azure-content-safety-content-moderation", "version": C.AZURE_POLICY_VERSION,
                     "params": {"request": {"showAssessment": True}}}],
}


def spec(name, policies):
    return {"apiVersion": "gateway.api-platform.wso2.com/v1", "kind": "LlmProvider", "metadata": {"name": name},
            "spec": {"displayName": name, "version": "v1.0", "context": f"/{name}", "template": "openai",
                     "upstream": {"url": C.MOCK_UPSTREAM_URL,
                                  "auth": {"type": "api-key", "header": "Authorization", "value": "Bearer mock"}},
                     "accessControl": {"mode": "allow_all"}, "globalPolicies": policies}}


def up(names):
    auth = (C.GATEWAY_MGMT_USER, C.GATEWAY_MGMT_PASSWORD)
    url = f"{C.GATEWAY_MGMT_URL}/llm-providers"
    for name in names:
        requests.delete(f"{url}/{name}", auth=auth, timeout=30)
        r = requests.post(url, auth=auth, data=json.dumps(spec(name, ROUTES[name])),
                          headers={"Content-Type": "application/yaml"}, timeout=30)
        print(f"deploy {name}: HTTP {r.status_code} {r.text[:160] if r.status_code >= 300 else ''}")
    for name in names:
        for _ in range(40):
            res = gateway(name, "Hello, what is the capital of France?")
            if res["decision"] == "allow":
                print(f"  {name} ready ({res['latency_s'] * 1000:.0f} ms)")
                break
            time.sleep(1.5)
        else:
            print(f"  {name} NOT ready: {res}. A policy that fails to start (for example missing keys in the "
                  "gateway config.toml) leaves the route answering 500 even though the deploy returned 201.")


def down():
    auth = (C.GATEWAY_MGMT_USER, C.GATEWAY_MGMT_PASSWORD)
    for name in ROUTES:
        r = requests.delete(f"{C.GATEWAY_MGMT_URL}/llm-providers/{name}", auth=auth, timeout=30)
        print(f"delete {name}: HTTP {r.status_code}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["down"]:
        down()
    elif sys.argv[1:2] == ["up"]:
        up(sys.argv[2:] or list(ROUTES))
    else:
        print(__doc__)
