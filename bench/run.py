"""Run one benchmark pass. Results append to results/<pass>__<system>.jsonl, so a pass can be stopped and resumed.

  P0  pilot: 7 prompts per category, every system, 4 in flight
  P1  direct scores: jev_default, jev_custom, azure, 10 in flight (feeds the threshold sweeps)
  P2  gateway run 1: gw_none, gw_jev, gw_azure, judge, one call at a time, order rotated per prompt
  P3  gateway run 2: the same as P2 (for decisions that flip between runs)
  P4  load: 300 prompts, 20 in flight, per system

  python -m bench.run P0|P1|P2|P3|P4 [--systems a,b] [--limit N] [--retry-errors]

Jev spend is tracked from recorded usage, and the run stops at JEV_BUDGET_USD.
"""
import argparse, collections, json, os, random, threading, time
from concurrent.futures import ThreadPoolExecutor

from bench import config as C
from bench import systems as S
from bench.data import load as load_prompts

SYSTEMS = {
    "jev_default": lambda t: S.jev_direct(t, S.default_questions()),
    "jev_custom": lambda t: S.jev_direct(t, S.custom_questions()),
    "azure": S.azure_cs_direct,
    "judge": S.judge,
    "gw_none": lambda t: S.gateway("bench-none", t),
    "gw_jev": lambda t: S.gateway("bench-jev", t),
    "gw_azure": lambda t: S.gateway("bench-azure", t),
}
JEV_SYSTEMS = {"jev_default", "jev_custom", "gw_jev"}
PASS_SYSTEMS = {
    "P0": ["jev_default", "jev_custom", "azure", "judge", "gw_none", "gw_jev", "gw_azure"],
    "P1": ["jev_default", "jev_custom", "azure"],
    "P2": ["gw_none", "gw_jev", "gw_azure", "judge"],
    "P3": ["gw_none", "gw_jev", "gw_azure", "judge"],
    "P4": ["gw_none", "gw_jev", "gw_azure", "judge"],
}
WORKERS = {"P0": 4, "P1": 10, "P4": 20}
lock = threading.Lock()
SPENT = {"tokens": 0}


def subset(rows, pass_id):
    if pass_id == "P0":
        rng, out, by = random.Random(7), [], collections.defaultdict(list)
        for r in rows:
            by[r["bucket"]].append(r)
        for b in sorted(by):
            out += rng.sample(by[b], 7)
        return out
    if pass_id == "P4":
        return random.Random(4).sample(rows, 300)
    return rows


def path(pass_id, system):
    return os.path.join(C.RESULTS_DIR, f"{pass_id}__{system}.jsonl")


def done_ids(pass_id, system, retry_errors):
    p = path(pass_id, system)
    if not os.path.exists(p):
        return set()
    ids = set()
    for line in open(p):
        r = json.loads(line)
        if not (retry_errors and r["decision"] == "error"):
            ids.add(r["id"])
    return ids


def est_tokens(text):
    """Gateway calls don't report Jev usage; estimate from the battery size plus the prompt."""
    return 430 + len(text) // 4


def jev_tokens_so_far():
    texts = {r["id"]: r["text"] for r in load_prompts()}
    by_id, total = {}, 0
    if not os.path.isdir(C.RESULTS_DIR):
        return 0
    for f in sorted(os.listdir(C.RESULTS_DIR)):
        system = f.split("__", 1)[-1].removesuffix(".jsonl")
        if system not in JEV_SYSTEMS:
            continue
        for line in open(os.path.join(C.RESULTS_DIR, f)):
            r = json.loads(line)
            tok = r.get("input_tokens")
            if tok:
                by_id.setdefault(r["id"], tok)
            else:
                tok = by_id.get(r["id"]) or est_tokens(texts.get(r["id"], ""))
            total += tok
    return total


def spent_usd():
    return SPENT["tokens"] * C.PRICES["jev_input_per_m"] / 1e6


def record(pass_id, system, row, res):
    res = dict(res, id=row["id"], ts=time.time())
    with lock:
        if system in JEV_SYSTEMS:  # errors count too, to stay conservative
            SPENT["tokens"] += res.get("input_tokens") or est_tokens(row["text"])
        with open(path(pass_id, system), "a") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
    return res


def run_concurrent(pass_id, system, rows, workers, retry_errors):
    done = done_ids(pass_id, system, retry_errors)
    todo = [r for r in rows if r["id"] not in done]
    print(f"{pass_id} {system}: {len(todo)} to run ({len(done)} done), {workers} in flight", flush=True)
    counts, t0 = collections.Counter(), time.time()

    def one(r):
        if system in JEV_SYSTEMS and spent_usd() >= C.JEV_BUDGET_USD:
            return None
        res = record(pass_id, system, r, SYSTEMS[system](r["text"]))
        with lock:
            counts[res["decision"]] += 1
            n = sum(counts.values())
            if n % 100 == 0:
                print(f"  {n}/{len(todo)} {dict(counts)} {time.time() - t0:.0f}s", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    print(f"  done {dict(counts)} in {time.time() - t0:.0f}s", flush=True)


def run_interleaved(pass_id, systems, rows, retry_errors):
    """One call at a time. Each prompt goes to every system, with the order rotated per prompt,
    so slow drift in network or gateway conditions hits every system alike."""
    done = {s: done_ids(pass_id, s, retry_errors) for s in systems}
    print(f"{pass_id} interleaved {systems}: {len(rows)} prompts", flush=True)
    counts, t0 = {s: collections.Counter() for s in systems}, time.time()
    for i, r in enumerate(rows):
        k = i % len(systems)
        for s in systems[k:] + systems[:k]:
            if r["id"] in done[s]:
                continue
            if s in JEV_SYSTEMS and spent_usd() >= C.JEV_BUDGET_USD:
                print("Jev budget cap reached, stopping", flush=True)
                return
            counts[s][record(pass_id, s, r, SYSTEMS[s](r["text"]))["decision"]] += 1
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(rows)} {time.time() - t0:.0f}s " +
                  " ".join(f"{s}={dict(c)}" for s, c in counts.items()), flush=True)
    print(f"  done in {time.time() - t0:.0f}s " + " ".join(f"{s}={dict(c)}" for s, c in counts.items()), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pass_id", choices=list(PASS_SYSTEMS))
    ap.add_argument("--systems", help="comma-separated subset of: " + ", ".join(SYSTEMS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-errors", action="store_true", help="re-run prompts whose earlier result was an error")
    a = ap.parse_args()
    os.makedirs(C.RESULTS_DIR, exist_ok=True)
    rows = subset(load_prompts(), a.pass_id)[:a.limit] if a.limit else subset(load_prompts(), a.pass_id)
    systems = a.systems.split(",") if a.systems else PASS_SYSTEMS[a.pass_id]
    SPENT["tokens"] = jev_tokens_so_far()
    print(f"Jev spend so far: ${spent_usd():.4f} ({SPENT['tokens']} input tokens), cap ${C.JEV_BUDGET_USD:.2f}", flush=True)
    if a.pass_id in ("P2", "P3"):
        run_interleaved(a.pass_id, systems, rows, a.retry_errors)
    else:
        for s in systems:
            run_concurrent(a.pass_id, s, rows, WORKERS[a.pass_id], a.retry_errors)
    print(f"Jev spend now: ${spent_usd():.4f} ({SPENT['tokens']} input tokens)", flush=True)


if __name__ == "__main__":
    main()
