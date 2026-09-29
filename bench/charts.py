"""Draw the article charts from a run's results.

  python -m bench.charts [runs/<name>]      (default: RESULTS_DIR's parent run folder)

Writes <run>/charts/accuracy.{png,svg} and <run>/charts/latency.{png,svg}. Every number is computed
from the run's results/*.jsonl, the same way bench.report computes it.
"""
import os, sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bench import config as C

SYSTEMS = [  # label, pass, system, colour, latency source (pass, system, paired-with-none?)
    ("Jev, default questions", "P2", "gw_jev", "#E8590C", ("P2", "gw_jev", True)),
    ("Jev, plus two custom questions", "P1", "jev_custom", "#FD7E14", ("P1", "jev_custom", False)),
    ("Azure AI Content Safety", "P2", "gw_azure", "#1971C2", ("P2", "gw_azure", True)),
    ("LLM judge (gpt-4o-mini)", "P2", "judge", "#495057", ("P2", "judge", False)),
]
FONT = ["Inter", "SF Pro Text", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
INK, MUTED, GRID = "#212529", "#6C757D", "#E9ECEF"


def style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": FONT, "font.size": 11,
        "axes.edgecolor": GRID, "axes.labelcolor": INK, "axes.titlecolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
        "svg.fonttype": "none", "figure.facecolor": "white", "axes.facecolor": "white",
    })


def numbers(rows):
    from bench.report import load, quant, summary, wilson
    out = []
    none2 = load("P2", "gw_none")
    for label, p, s, colour, (lp, ls, paired) in SYSTEMS:
        res = load(p, s)
        m = summary(rows, res)
        n_u, n_b = m["tp"] + m["fn"], m["fp"] + m["tn"]
        lat_res = load(lp, ls)
        if paired:
            lat = [lat_res[i]["latency_s"] - none2[i]["latency_s"] for i in lat_res
                   if i in none2 and lat_res[i]["decision"] != "error"]
        else:
            lat = [x["latency_s"] for x in lat_res.values() if x["decision"] != "error"]
        out.append({
            "label": label, "colour": colour,
            "caught": 100 * m["tp"] / n_u, "caught_ci": [100 * v for v in wilson(m["tp"], n_u)],
            "blocked": 100 * m["fp"] / n_b, "blocked_ci": [100 * v for v in wilson(m["fp"], n_b)],
            "p50": 1000 * quant(lat, .5), "p90": 1000 * quant(lat, .9), "direct": not paired and s != "judge",
        })
    return out


def accuracy_chart(data, n, path):
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=200)
    # label anchor (data coordinates), horizontal and vertical alignment
    place = {"Jev, default questions": (10.2, 67.2, "left", "top"),
             "Jev, plus two custom questions": (12.9, 83.2, "right", "bottom"),
             "Azure AI Content Safety": (7.7, 36.9, "left", "bottom"),
             "LLM judge (gpt-4o-mini)": (20.3, 88.6, "center", "bottom")}
    for d in data:
        xerr = [[d["blocked"] - d["blocked_ci"][0]], [d["blocked_ci"][1] - d["blocked"]]]
        yerr = [[d["caught"] - d["caught_ci"][0]], [d["caught_ci"][1] - d["caught"]]]
        ax.errorbar(d["blocked"], d["caught"], xerr=xerr, yerr=yerr, fmt="none", ecolor=d["colour"],
                    elinewidth=1, alpha=0.35, capsize=0, zorder=2)
        ax.scatter(d["blocked"], d["caught"], s=170, color=d["colour"], edgecolor="white", linewidth=1.5, zorder=3)
        x, y, ha, va = place[d["label"]]
        star = "¹" if d["direct"] else ""
        ax.text(x, y, f"{d['label']}\n{d['caught']:.1f}% caught · {d['blocked']:.1f}% benign blocked\n"
                f"adds {d['p50']:,.0f} ms at p50{star}", ha=ha, va=va, fontsize=8.6, color=INK,
                linespacing=1.35, zorder=4)
    ax.set_xlim(0, 26)
    ax.set_ylim(20, 100)
    ax.set_xlabel("Benign prompts wrongly blocked (%), lower is better", fontsize=10.5)
    ax.set_ylabel("Unsafe prompts caught (%), higher is better", fontsize=10.5)
    ax.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.text(0.5, 98.5, "Better: up and to the left", ha="left", va="top", fontsize=8.6, color=MUTED, style="italic")
    fig.text(0.07, 0.955, "Catching unsafe prompts vs. blocking legitimate ones", fontsize=14, weight="bold", color=INK)
    fig.text(0.07, 0.915, f"{n:,} labelled prompts, request side. Faint bars are 95% confidence intervals.",
             fontsize=9.5, color=MUTED)
    fig.text(0.07, 0.02, "¹ Measured calling Jev directly. The LLM judge includes Azure OpenAI's built-in content filter. "
             "Benchmark run 28 Sep 2026.", fontsize=7.8, color=MUTED)
    fig.subplots_adjust(left=0.1, right=0.97, top=0.87, bottom=0.14)
    save(fig, path)


def latency_chart(data, path):
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
    labels = [d["label"] + ("¹" if d["direct"] else "") for d in data][::-1]
    ys = range(len(data))
    for y, d in zip(ys, data[::-1]):
        ax.barh(y, d["p90"], height=0.56, color=d["colour"], alpha=0.28, zorder=2)
        ax.barh(y, d["p50"], height=0.56, color=d["colour"], zorder=3)
        ax.text(d["p50"] - 30, y, f"{d['p50']:,.0f}", va="center", ha="right", fontsize=9, color="white",
                weight="bold", zorder=4)
        ax.text(d["p90"] + 30, y, f"{d['p90']:,.0f} ms", va="center", ha="left", fontsize=9, color=INK, zorder=4)
    ax.set_yticks(list(ys))
    ax.set_yticklabels(labels, fontsize=10, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(d["p90"] for d in data) * 1.18)
    ax.set_xlabel("Latency added per request (ms)", fontsize=10.5)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.spines["left"].set_visible(False)
    fig.text(0.02, 0.94, "Latency each guardrail adds to a request", fontsize=14, weight="bold", color=INK)
    fig.text(0.02, 0.885, "Solid: median (p50). Light: p90. Through WSO2 AI Gateway, one request at a time.",
             fontsize=9.5, color=MUTED)
    fig.text(0.02, 0.025, "¹ Measured calling Jev directly. Benchmark run 28 Sep 2026.", fontsize=7.8, color=MUTED)
    fig.subplots_adjust(left=0.33, right=0.97, top=0.82, bottom=0.2)
    save(fig, path)


def save(fig, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path + ".png", facecolor="white")
    fig.savefig(path + ".svg", facecolor="white")
    plt.close(fig)
    print(f"wrote {path}.png and .svg")


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(C.RESULTS_DIR)
    C.RESULTS_DIR = os.path.join(run, "results")
    from bench.data import load as load_prompts
    rows = load_prompts()
    style()
    data = numbers(rows)
    for d in data:
        print(f"  {d['label']:32} caught {d['caught']:.1f}%  blocked {d['blocked']:.1f}%  p50 {d['p50']:.0f}  p90 {d['p90']:.0f}")
    accuracy_chart(data, len(rows), os.path.join(run, "charts", "accuracy"))
    latency_chart(data, os.path.join(run, "charts", "latency"))


if __name__ == "__main__":
    main()
