# Run 2026-09-28

The first full run. The results are in [REPORT.md](REPORT.md), the decisions by prompt id are in [per_prompt.csv](per_prompt.csv), and every raw call is in [results/](results/).

## Setup

- **Prompt set:** `data/bench_v1.jsonl`, 1,197 prompts, matching `data/manifest_v1.csv`.
- **Gateway:** WSO2 AI Gateway 1.2.0 in Docker Desktop on an Apple silicon MacBook, on a laptop in UTC+5:30.
- **Policies:**
  - `typesafe-jev-content-safety` v0.8.0, built as a local policy from wso2/gateway-controllers#309, with request-side defaults.
  - `azure-content-safety-content-moderation` v1.0.2, with its defaults.
- **Jev:** `https://api.typesafe.ai`, model `jev-latest`.
- **Azure AI Content Safety:** Standard S0 in East US.
- **LLM judge:** Azure OpenAI `gpt-4o-mini` (2024-07-18), reached through the gateway's LLM provider route, which has only api-key-auth. Azure OpenAI's content filter was on for the deployment.
- **Network from the test machine** (median TCP + TLS connect): Jev 114 ms, Azure OpenAI 894 ms, Azure Content Safety 921 ms. Connect times to both Azure services were about 8 times Jev's, which adds to their measured latency.
- **Passes:** P0 to P4 as described in the README. The two calls that errored (one Azure Content Safety read timeout in P1, one judge read timeout in P2) were re-run with `--retry-errors`. The report uses the re-run results.
- **Jev spend:** $0.137 of credit, computed from recorded usage. It was consistent with the change in the TypeSafe dashboard balance, checked once during the run.

## Reading the results

- **The judge row is gpt-4o-mini plus Azure OpenAI's built-in content filter.** The filter refused 310 of the 1,197 judge calls before the model answered: 258 on unsafe prompts and 52 on benign ones. On the 887 prompts the model answered itself, it caught 74.3% of unsafe prompts and blocked 12.8% of benign ones.
- **Azure Content Safety has no jailbreak or harmful-request categories.** Its low overall catch rate comes mostly from those two categories: it caught 4.7% of jailbreaks and 11.5% of harmful requests. On self-harm, sexual and hate content it does well.
- **Jev's defaults don't include a hate or sexual question.** The customised variant adds one of each, which raises hate/harassment from 32% to 78% and sexual from 70% to 98%. Both questions were written before the run.
- **Load latency is dominated by this laptop.** At 20 requests in flight, the route with no guardrail already has a p50 of 911 ms, from Docker Desktop plus the single-process Python mock model. The useful figure is what each guardrail policy adds on top of that: at p50, Jev and Azure each add about 90 ms. The judge calls go straight to Azure OpenAI through the gateway, not to the mock, so the baseline doesn't apply to them: the judge call alone took 1,643 ms at p50 under load. Run the load pass on a proper host before quoting absolute load numbers.
- **The appendix lists 81 prompts that all three systems got "wrong".** Most are in-the-wild jailbreak prompts (22), OpenAI moderation hate/harassment rows (20) and XSTest unsafe contrast prompts (13). They are worth a manual look for label noise. Nothing was relabelled.
