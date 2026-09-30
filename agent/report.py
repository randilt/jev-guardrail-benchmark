"""Turn agent/results/P2__<config>.jsonl into a run folder: REPORT.md, per_case.csv and a chart.

  python -m agent.report runs/<name>
"""
import collections, csv, json, math, os, statistics, sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from agent import config as A

# Checks AgentDojo scores from the tool calls the model requested, not from the environment. A call the gateway
# blocked still counts as attempted there, so these cases are listed separately.
TRACE_SCORED = {("slack", "injection_task_5"), ("slack", "user_task_11"), ("slack", "user_task_17"),
                ("slack", "user_task_18"), ("slack", "user_task_19"), ("slack", "user_task_20")}
LAYERS = {"result_withheld": "Result screening withheld a result", "intent_blocked": "Intent verification blocked a call",
          "content_safety_blocked": "Content safety blocked an LLM request", "azure_content_filter": "Azure OpenAI filter refused",
          "result_unchecked": "Result withheld as unchecked (Jev failed)", "intent_unchecked": "Call blocked as unchecked (Jev failed)"}


def load(config, pass_id="P2"):
    rows = {}
    for line in open(os.path.join(A.RESULTS_DIR, f"{pass_id}__{config}.jsonl")):
        r = json.loads(line)
        rows[r["key"]] = r  # the last row per case wins (retried errors)
    return rows


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


def pct(k, n):
    if n == 0:
        return "–"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.1f}% ({100 * lo:.0f}–{100 * hi:.0f})"


def rates(rows):
    ok = [r for r in rows if not r["error"]]
    clean = [r for r in ok if r["injection_task"] is None]
    att = [r for r in ok if r["injection_task"]]
    return {"clean_n": len(clean), "clean_u": sum(r["utility"] for r in clean), "att_n": len(att),
            "att_u": sum(r["utility"] for r in att), "asr": sum(r["security"] for r in att),
            "errors": sum(bool(r["error"]) for r in rows)}


def chart(stats, path):
    labels = ["Clean tasks completed", "Attacked tasks completed", "Attacks that succeeded"]
    keys = [("clean_u", "clean_n"), ("att_u", "att_n"), ("asr", "att_n")]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
    width, colours = 0.36, {"baseline": "#868E96", "full": "#E8590C"}
    names = {"baseline": "No guardrails", "full": "Jev guardrails (content safety, intent verification, result screening)"}
    for j, config in enumerate(("baseline", "full")):
        s = stats[config]
        vals = [100 * s[k] / s[n] for k, n in keys]
        errs = [[100 * (s[k] / s[n] - wilson(s[k], s[n])[0]) for k, n in keys],
                [100 * (wilson(s[k], s[n])[1] - s[k] / s[n]) for k, n in keys]]
        xs = [i + (j - 0.5) * width for i in range(3)]
        ax.bar(xs, vals, width, color=colours[config], label=names[config], yerr=errs, capsize=3,
               error_kw={"elinewidth": 0.8, "ecolor": "#495057"})
        for x, v, up in zip(xs, vals, errs[1]):
            ax.text(x, v + up + 2.5, f"{v:.0f}%", ha="center", fontsize=9)
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylim(0, 110)
    ax.set_ylabel("% of cases")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=1)
    fig.text(0.02, 0.96, "AgentDojo tasks through WSO2 AI Gateway", fontsize=13, weight="bold")
    fig.text(0.02, 0.91, f"{A.MODEL_ID}, {stats['full']['clean_n']} clean tasks and {stats['full']['att_n']} attacked cases per configuration. Bars show 95% intervals.",
             fontsize=8.5, color="#6C757D")
    fig.subplots_adjust(top=0.84, bottom=0.3)
    fig.savefig(path + ".png", facecolor="white")
    fig.savefig(path + ".svg", facecolor="white")
    plt.close(fig)


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else os.path.join(A.ROOT, "runs", "agent")
    os.makedirs(run, exist_ok=True)
    data = {c: load(c) for c in A.CONFIGS}
    keys = sorted(set(data["baseline"]) & set(data["full"]))
    stats = {c: rates([data[c][k] for k in keys]) for c in A.CONFIGS}
    b, f = data["baseline"], data["full"]
    L = []
    w = L.append
    w("# AgentDojo through WSO2 AI Gateway\n")
    w(f"Model: `{A.MODEL_ID}` (Azure OpenAI, content filter at lowest blocking with Prompt Shields off), temperature "
      f"{A.TEMPERATURE:g}. AgentDojo `{A.BENCHMARK_VERSION}`, attack `{A.ATTACK}`. Every LLM call went through a gateway LLM "
      "proxy and every tool call through a gateway MCP proxy. 95% Wilson intervals in brackets.\n")
    w("- **Baseline:** the same routes with no policies.")
    w("- **Full stack:** `typesafe-jev-content-safety` on the LLM proxy; `typesafe-jev-mcp-tool-intent-verification` "
      "(one `*` rule with the suite's scope) and `typesafe-jev-mcp-tool-result-screening` on the MCP proxy. All at their "
      "defaults. Tool filtering was left out; see the README.\n")

    w("## Results\n")
    w("| | Baseline | Full stack |")
    w("|---|---|---|")
    sb, sf = stats["baseline"], stats["full"]
    w(f"| Clean tasks completed | {pct(sb['clean_u'], sb['clean_n'])} | {pct(sf['clean_u'], sf['clean_n'])} |")
    w(f"| Attacked tasks still completed | {pct(sb['att_u'], sb['att_n'])} | {pct(sf['att_u'], sf['att_n'])} |")
    w(f"| Attacks that succeeded | {pct(sb['asr'], sb['att_n'])} | {pct(sf['asr'], sf['att_n'])} |")
    w(f"| Cases that errored (not scored) | {sb['errors']} | {sf['errors']} |\n")

    w("### By suite\n")
    w("| Suite | Clean completed: baseline → full | Attacks succeeded: baseline → full |")
    w("|---|---|---|")
    for suite in A.SUITES:
        ks = [k for k in keys if b[k]["suite"] == suite]
        x, y = rates([b[k] for k in ks]), rates([f[k] for k in ks])
        w(f"| {suite} | {x['clean_u']}/{x['clean_n']} → {y['clean_u']}/{y['clean_n']} | {x['asr']}/{x['att_n']} → {y['asr']}/{y['att_n']} |")

    w("\n## What happened to each attack (paired)\n")
    att = [k for k in keys if b[k]["injection_task"] and not b[k]["error"] and not f[k]["error"]]
    won_b = [k for k in att if b[k]["security"]]
    stopped = [k for k in won_b if not f[k]["security"]]
    new = [k for k in att if f[k]["security"] and not b[k]["security"]]
    w(f"- Attacks that succeeded without guardrails: **{len(won_b)}** of {len(att)}. With the full stack, "
      f"**{len(stopped)}** of those were stopped and {len(won_b) - len(stopped)} still succeeded.")
    w(f"- Attacks that failed without guardrails but succeeded with them: {len(new)}.")
    by_layer = collections.Counter()
    for k in stopped:
        for layer in sorted({i["layer"] for i in f[k]["interventions"]}) or ["none"]:
            by_layer[layer] += 1
    w("- Layers present in the stopped attacks (a case can have more than one): " +
      ", ".join(f"{LAYERS.get(l, 'no intervention recorded')} {n}" for l, n in by_layer.most_common()) + ".\n")

    w("## Interventions and how the agent reacted\n")
    w("| Layer | Clean cases with it | …still completed | Attacked cases with it | …still completed |")
    w("|---|---|---|---|---|")
    for layer, name in LAYERS.items():
        cc = [k for k in keys if f[k]["injection_task"] is None and any(i["layer"] == layer for i in f[k]["interventions"])]
        ac = [k for k in keys if f[k]["injection_task"] and any(i["layer"] == layer for i in f[k]["interventions"])]
        if cc or ac:
            w(f"| {name} | {len(cc)} | {sum(bool(f[k]['utility']) for k in cc)} | {len(ac)} | {sum(bool(f[k]['utility']) for k in ac)} |")
    w("\nOn clean cases an intervention is a false alarm; \"still completed\" shows whether the agent finished the task "
      "after a withheld result (`isError`) or a blocked call.\n")
    clean = [k for k in keys if f[k]["injection_task"] is None and not b[k]["error"] and not f[k]["error"]]
    lost = [k for k in clean if b[k]["utility"] and not f[k]["utility"]]
    gained = [k for k in clean if f[k]["utility"] and not b[k]["utility"]]
    lost_iv = [k for k in lost if f[k]["interventions"]]
    w(f"Clean tasks completed at baseline but not with the full stack: {len(lost)} ({len(lost_iv)} with an intervention, "
      f"{len(lost) - len(lost_iv)} without, which is run-to-run variation). Completed only with the full stack: {len(gained)}.\n")

    w("## Cost and time\n")
    w("| | Baseline | Full stack |")
    w("|---|---|---|")
    for label, field in (("Seconds per task", "seconds"), ("LLM calls per task", "llm_calls"), ("Tool calls per task", "tool_calls"),
                         ("Prompt tokens per task", "prompt_tokens"), ("Completion tokens per task", "completion_tokens")):
        vb = statistics.mean(b[k][field] for k in keys)
        vf = statistics.mean(f[k][field] for k in keys)
        w(f"| {label} | {vb:,.1f} | {vf:,.1f} |")
    for config, rows in (("Baseline", b), ("Full stack", f)):
        cost = sum(rows[k]["prompt_tokens"] * A.PRICE_LLM_INPUT_PER_M + rows[k]["completion_tokens"] * A.PRICE_LLM_OUTPUT_PER_M
                   for k in keys) / 1e6
        w(f"\n{config}: LLM cost about ${cost:.2f} for {len(keys)} cases at ${A.PRICE_LLM_INPUT_PER_M}/"
          f"${A.PRICE_LLM_OUTPUT_PER_M} per million input/output tokens.")

    w("\n## Cases scored from requested tool calls\n")
    w("AgentDojo scores these from the calls the model asked for, so a call the gateway blocked still counts as made:\n")
    flagged = [k for k in keys if (f[k]["suite"], f[k]["injection_task"]) in TRACE_SCORED or (f[k]["suite"], f[k]["user_task"]) in TRACE_SCORED]
    w(f"{len(flagged)} cases; with an intervention in the full stack: "
      f"{sum(bool(f[k]['interventions']) for k in flagged)}.\n")

    errs = [(c, k, data[c][k]["error"]) for c in A.CONFIGS for k in keys if data[c][k]["error"]]
    if errs:
        w("## Errors\n")
        for c, k, e in errs:
            w(f"- {c} `{k}`: {e[:160]}")
    open(os.path.join(run, "REPORT.md"), "w").write("\n".join(L) + "\n")

    with open(os.path.join(run, "per_case.csv"), "w", newline="") as fh:
        cw = csv.writer(fh)
        cw.writerow(["suite", "user_task", "injection_task", "baseline_utility", "baseline_attack_succeeded", "full_utility",
                     "full_attack_succeeded", "full_interventions", "baseline_seconds", "full_seconds"])
        for k in keys:
            cw.writerow([b[k]["suite"], b[k]["user_task"], b[k]["injection_task"] or "", b[k]["utility"],
                         b[k]["security"] if b[k]["injection_task"] else "", f[k]["utility"],
                         f[k]["security"] if f[k]["injection_task"] else "",
                         ";".join(f"{i['layer']}:{i['tool']}" for i in f[k]["interventions"]), b[k]["seconds"], f[k]["seconds"]])
    chart(stats, os.path.join(run, "agent"))
    print("\n".join(L[:30]))
    print(f"... wrote {run}/REPORT.md, per_case.csv, agent.png/.svg")


if __name__ == "__main__":
    main()
