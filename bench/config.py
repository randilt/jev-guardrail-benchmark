"""Settings, read from environment variables or a .env file in the repo root.

Secrets (API keys) are only ever read, never printed or written to results.
See .env.example for every setting.
"""
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def get(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _gateway_toml():
    """Optional convenience: read Jev and Azure credentials from a gateway config.toml."""
    path = get("GATEWAY_CONFIG_TOML")
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


_toml = _gateway_toml()


def secret(env_name, toml_name):
    value = get(env_name) or _toml.get(toml_name)
    if not value:
        raise SystemExit(f"{env_name} is not set (in .env, the environment, or GATEWAY_CONFIG_TOML)")
    return value


# Jev (TypeSafe AI)
JEV_BASE_URL = get("JEV_BASE_URL") or _toml.get("jev_base_url") or "https://api.typesafe.ai"
JEV_MODEL = get("JEV_MODEL") or _toml.get("jev_model") or "jev-latest"
jev_api_key = lambda: secret("JEV_API_KEY", "jev_apikey")

# Azure AI Content Safety
azure_cs_endpoint = lambda: secret("AZURE_CS_ENDPOINT", "azurecontentsafety_endpoint").rstrip("/")
azure_cs_key = lambda: secret("AZURE_CS_KEY", "azurecontentsafety_key")

# LLM judge: any OpenAI-compatible chat completions URL (the gateway route or Azure OpenAI directly)
judge_url = lambda: secret("JUDGE_URL", "")
JUDGE_KEY_HEADER = get("JUDGE_KEY_HEADER", "api-key")
judge_key = lambda: secret("JUDGE_KEY", "")
JUDGE_LABEL = get("JUDGE_LABEL", "gpt-4o-mini")
JUDGE_UPSTREAM_HOST = get("JUDGE_UPSTREAM_HOST")  # for the network probe when the judge goes through a gateway

# WSO2 AI Gateway
GATEWAY_URL = get("GATEWAY_URL", "https://localhost:8443").rstrip("/")
GATEWAY_TLS_VERIFY = get("GATEWAY_TLS_VERIFY", "false").lower() == "true"
GATEWAY_MGMT_URL = get("GATEWAY_MGMT_URL", "http://localhost:9090/api/management/v1").rstrip("/")
GATEWAY_MGMT_USER = get("GATEWAY_MGMT_USER", "admin")
GATEWAY_MGMT_PASSWORD = get("GATEWAY_MGMT_PASSWORD", "admin")
MOCK_UPSTREAM_URL = get("MOCK_UPSTREAM_URL", "http://bench-mock:8000/v1")
JEV_POLICY_VERSION = get("JEV_POLICY_VERSION", "v0")
AZURE_POLICY_VERSION = get("AZURE_POLICY_VERSION", "v1")

# Where the Jev question battery comes from. Default: the copy in config/ (policy v0.8.0 defaults).
JEV_QUESTIONS_FILE = get("JEV_QUESTIONS_FILE", os.path.join(ROOT, "config", "jev_questions.yaml"))
JEV_POLICY_DEFINITION = get("JEV_POLICY_DEFINITION")  # optional: read defaults from a policy-definition.yaml

# Budget and prices (check the pricing pages before publishing numbers)
JEV_BUDGET_USD = float(get("JEV_BUDGET_USD", "1.00"))
PRICES = {
    "jev_input_per_m": float(get("PRICE_JEV_INPUT_PER_M", "0.042")),
    "judge_input_per_m": float(get("PRICE_JUDGE_INPUT_PER_M", "0.15")),
    "judge_output_per_m": float(get("PRICE_JUDGE_OUTPUT_PER_M", "0.60")),
    "azure_cs_per_1k_records": float(get("PRICE_AZURE_CS_PER_1K_RECORDS", "0.375")),
}

DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
BENCH_FILE = os.path.join(DATA_DIR, "bench_v1.jsonl")
MANIFEST_FILE = os.path.join(DATA_DIR, "manifest_v1.csv")
RESULTS_DIR = get("RESULTS_DIR", os.path.join(ROOT, "results"))
