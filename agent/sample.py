"""Build (or check) the frozen case lists in agent/data/sample_v1.json.

  P0  harness check: AgentDojo v1 banking, all 16 user tasks clean + 40 attacked pairs
  P1  full-stack pilot: v1.2.2, per suite 2 clean + 3 attacked
  P2  core sample: v1.2.2, all 97 user tasks clean + 300 attacked pairs
      (workspace 100, travel 70, banking 70, slack 60), every injection task at least once

  python -m agent.sample build | check
"""
import json
import random
import sys

from agentdojo.task_suite.load_suites import get_suite

from agent import config as A

P2_QUOTA = {"workspace": 100, "travel": 70, "banking": 70, "slack": 60}


def attacked_pairs(rng, suite, quota):
    """quota pairs, covering every injection task first, then random pairs without repeats."""
    users, injections = sorted(suite.user_tasks), sorted(suite.injection_tasks)
    pairs = [(u, i) for u in users for i in injections]
    rng.shuffle(pairs)
    picked, seen = [], set()
    for inj in injections:
        pair = next(p for p in pairs if p[1] == inj and p not in seen)
        picked.append(pair)
        seen.add(pair)
    for p in pairs:
        if len(picked) >= quota:
            break
        if p not in seen:
            picked.append(p)
            seen.add(p)
    return sorted(picked)


def cases(version, suite_name, clean, attacked):
    out = [{"suite": suite_name, "user_task": u, "injection_task": None} for u in clean]
    out += [{"suite": suite_name, "user_task": u, "injection_task": i} for u, i in attacked]
    return out


def build():
    sample = {"attack": A.ATTACK, "passes": {}}
    rng = random.Random(7)
    s = get_suite("v1", "banking")
    sample["passes"]["P0"] = {"version": "v1", "cases": cases("v1", "banking", sorted(s.user_tasks), attacked_pairs(rng, s, 40))}

    rng = random.Random(11)
    p1 = []
    for name in A.SUITES:
        s = get_suite(A.BENCHMARK_VERSION, name)
        p1 += cases(A.BENCHMARK_VERSION, name, rng.sample(sorted(s.user_tasks), 2), attacked_pairs(rng, s, 3)[:3])
    sample["passes"]["P1"] = {"version": A.BENCHMARK_VERSION, "cases": p1}

    rng = random.Random(42)
    p2 = []
    for name in A.SUITES:
        s = get_suite(A.BENCHMARK_VERSION, name)
        p2 += cases(A.BENCHMARK_VERSION, name, sorted(s.user_tasks), attacked_pairs(rng, s, P2_QUOTA[name]))
    sample["passes"]["P2"] = {"version": A.BENCHMARK_VERSION, "cases": p2}

    json.dump(sample, open(A.SAMPLE_FILE, "w"), indent=1)
    check()


def load(pass_id):
    p = json.load(open(A.SAMPLE_FILE))["passes"][pass_id]
    return p["version"], p["cases"]


def check():
    sample = json.load(open(A.SAMPLE_FILE))
    for pass_id, p in sample["passes"].items():
        cs = p["cases"]
        keys = {(c["suite"], c["user_task"], c["injection_task"]) for c in cs}
        assert len(keys) == len(cs), f"{pass_id}: duplicate cases"
        clean = sum(c["injection_task"] is None for c in cs)
        print(f"{pass_id} ({p['version']}): {len(cs)} cases, {clean} clean, {len(cs) - clean} attacked")
        for name in sorted({c["suite"] for c in cs}):
            s = get_suite(p["version"], name)
            injs = {c["injection_task"] for c in cs if c["suite"] == name and c["injection_task"]}
            n_clean = sum(1 for c in cs if c["suite"] == name and c["injection_task"] is None)
            print(f"  {name}: {n_clean} clean, {sum(1 for c in cs if c['suite'] == name and c['injection_task'])} attacked, "
                  f"injection tasks covered {len(injs)}/{len(s.injection_tasks)}")
            if pass_id in ("P0", "P2"):
                assert len(injs) == len(s.injection_tasks), f"{pass_id} {name}: not every injection task is covered"
            if pass_id == "P2":
                assert n_clean == len(s.user_tasks), f"P2 {name}: not every user task is run clean"
    print("sample OK")


if __name__ == "__main__":
    {"build": build, "check": check}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
