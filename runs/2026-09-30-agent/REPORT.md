# AgentDojo through WSO2 AI Gateway

Model: `gpt-4o-2024-11-20` (Azure OpenAI, content filter at lowest blocking with Prompt Shields off), temperature 0. AgentDojo `v1.2.2`, attack `important_instructions`. Every LLM call went through a gateway LLM proxy and every tool call through a gateway MCP proxy. 95% Wilson intervals in brackets.

- **Baseline:** the same routes with no policies.
- **Full stack:** `typesafe-jev-content-safety` on the LLM proxy; `typesafe-jev-mcp-tool-intent-verification` (one `*` rule with the suite's scope) and `typesafe-jev-mcp-tool-result-screening` on the MCP proxy. All at their defaults. Tool filtering was left out; see the README.

## Results

| | Baseline | Full stack |
|---|---|---|
| Clean tasks completed | 77.3% (68–85) | 77.3% (68–85) |
| Attacked tasks still completed | 46.7% (41–52) | 16.7% (13–21) |
| Attacks that succeeded | 56.3% (51–62) | 0.0% (0–1) |
| Cases that errored (not scored) | 0 | 0 |

### By suite

| Suite | Clean completed: baseline → full | Attacks succeeded: baseline → full |
|---|---|---|
| workspace | 28/40 → 27/40 | 28/100 → 0/100 |
| travel | 14/20 → 15/20 | 36/70 → 0/70 |
| banking | 14/16 → 14/16 | 50/70 → 0/70 |
| slack | 19/21 → 19/21 | 55/60 → 0/60 |

## What happened to each attack (paired)

- Attacks that succeeded without guardrails: **169** of 300. With the full stack, **169** of those were stopped and 0 still succeeded.
- Attacks that failed without guardrails but succeeded with them: 0.
- Layers present in the stopped attacks (a case can have more than one): Result screening withheld a result 168, Content safety blocked an LLM request 1, no intervention recorded 1, Intent verification blocked a call 1.

## Interventions and how the agent reacted

| Layer | Clean cases with it | …still completed | Attacked cases with it | …still completed |
|---|---|---|---|---|
| Result screening withheld a result | 2 | 0 | 269 | 44 |
| Intent verification blocked a call | 2 | 1 | 3 | 0 |
| Content safety blocked an LLM request | 0 | 0 | 3 | 0 |

On clean cases an intervention is a false alarm; "still completed" shows whether the agent finished the task after a withheld result (`isError`) or a blocked call.

Clean tasks completed at baseline but not with the full stack: 5 (1 with an intervention, 4 without, which is run-to-run variation). Completed only with the full stack: 5.

## Cost and time

| | Baseline | Full stack |
|---|---|---|
| Seconds per task | 10.9 | 11.6 |
| LLM calls per task | 4.5 | 3.9 |
| Tool calls per task | 4.8 | 3.7 |
| Prompt tokens per task | 11,081.1 | 7,745.2 |
| Completion tokens per task | 265.2 | 178.1 |

Baseline: LLM cost about $12.05 for 397 cases at $2.5/$10.0 per million input/output tokens.

Full stack: LLM cost about $8.39 for 397 cases at $2.5/$10.0 per million input/output tokens.

## Cases scored from requested tool calls

AgentDojo scores these from the calls the model asked for, so a call the gateway blocked still counts as made:

27 cases; with an intervention in the full stack: 24.

