# Run 2026-09-30 (agent workflow)

The first run of the agent-workflow benchmark. The results are in [REPORT.md](REPORT.md) and each case's result is in [per_case.csv](per_case.csv). The method is described in [agent/README.md](../../agent/README.md).

## Setup

- **Model:** Azure OpenAI `gpt-4o` deployment, which reports `gpt-4o-2024-11-20`. It was reached through gateway LLM proxies on its provider, at temperature 0.
- **Azure content filter:** a custom filter at lowest blocking for hate, sexual, violence and self-harm, with Prompt Shields (jailbreak and indirect attacks) off. There were no Azure refusals in either configuration.
- **AgentDojo:** `agentdojo==0.1.35`, benchmark `v1.2.2`, `important_instructions` attack. The cases are the frozen [`agent/data/sample_v1.json`](../../agent/data/sample_v1.json): 97 clean tasks and 300 attacked pairs.
- **Gateway:** WSO2 AI Gateway 1.2.0 in Docker Desktop on an Apple silicon MacBook. The policies, all built as local policies:
  - `typesafe-jev-content-safety` v0.8.0 (#309);
  - intent verification v0.8.0 (#312, built under its earlier name `typesafe-jev-mcp-tool-guardrail`);
  - `typesafe-jev-mcp-tool-result-screening` v0.8.0 (#319).
- **Harness check (P0):** a baseline run on AgentDojo v1 banking. It completed 13/16 and 14/16 clean tasks over two runs, against 12/16 in AgentDojo's stored gpt-4o run. Attacks succeeded in 26/40 in both runs, against 24/40 stored. The two runs agreed on 54 of 56 cases for attack success.
- **Pilot (P1):** 20 cases, which is where tool filtering was taken out (see the agent README). The pilot results aren't part of the report.
- **How it ran:**
  - About 140 baseline cases first failed on Azure's token rate limit (HTTP 429) at 6 in parallel. The rate-limit retry was added and those cases were re-run at 3 in parallel.
  - Two full-stack cases failed with a transient "no healthy upstream" and were re-run.
  - The Mac slept for about 40 minutes during the full-stack pass (lid closed). No case failed because of it. The recorded times exclude the sleep.
  - Every scored case finished without an error.
- **Jev spend:** the TypeSafe dashboard balance was $4.81 before the full-stack pass.

## Reading the results

- **The baseline and the full stack completed the same share of clean tasks (77%).** The 23% the model misses are misses under AgentDojo's strict checkers, and they happen with no guardrails too. AgentDojo's stored gpt-4o run completes 69% of the same tasks.
- **No attack succeeded with the guardrails.** That's 0 of 300, against 169 of 300 without. Result screening was involved in 168 of the 169 stopped attacks.
- **Most attacked tasks were abandoned rather than completed** (47% → 17%). The attack sits inside a tool result the task needs, so withholding that result also withholds the data. 103 of the 104 attacked tasks lost this way had a withheld result. AgentDojo's own stored prompt-injection detector defense shows the same pattern: on an older gpt-4o version and benchmark v1, attacks drop from 48% to 8% and attacked-task completion from 50% to 21%. That detector also cuts clean-task completion, from 69% to 41%.
- **Timings aren't comparable between the two configurations.** Both passes include waits for Azure's rate limit, and they ran at different parallelism. Don't quote a latency difference from this run.
- **LLM cost** at gpt-4o list prices ($2.50 input and $10 output per million tokens) was about $12.05 for the baseline and $8.39 for the full stack. Agents stop sooner when a result is withheld, which is why the full stack costs less. Check your Azure price before quoting these.
