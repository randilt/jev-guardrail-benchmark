"""Run one pass of the agent benchmark for one gateway configuration.

  python -m agent.run P0|P1|P2 --config baseline|full [--workers N] [--limit N]

Each case is one AgentDojo task run: a user task alone (clean), or with one injection task (attacked,
important_instructions). AgentDojo scores it (utility, security) and writes its own trace under
results/<pass>/<config>/; this script also appends one row per case to results/<pass>__<config>.jsonl,
with the gateway interventions, token usage and timings. Finished cases are skipped on a re-run.
"""
import argparse
import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import run_task_with_injection_tasks, run_task_without_injection_tasks
from agentdojo.logging import LOGGER_STACK, Logger
from agentdojo.task_suite.load_suites import get_suite

from agent import config as A
from agent import pipeline as P
from agent.mcp_server import REGISTRY, serve
from agent.sample import load as load_sample

lock = threading.Lock()


class TraceDelegate(Logger):
    """A quiet parent logger that only tells AgentDojo's TraceLogger where to write. (NullLogger doesn't put
    itself on the logger stack, so TraceLogger would never find it.)"""

    def __init__(self, logdir):
        self.logdir = logdir
        self.messages = []

    def log(self, *args, **kwargs):
        pass


def case_key(c):
    return f"{c['suite']}/{c['user_task']}/{c['injection_task'] or 'none'}"


def run_case(case, config, version, logdir, pipelines, attacks):
    # AgentDojo keeps its logger stack in a ContextVar whose default list is shared; give each thread its own.
    LOGGER_STACK.set([])
    suite = get_suite(version, case["suite"])
    pipeline = pipelines[case["suite"]]
    sid = P.open_session(pipeline.mcp_url)
    ctx = P.TaskContext(case["suite"], config, sid)
    P.set_context(ctx)
    t0 = time.perf_counter()
    row = {"key": case_key(case), **case, "config": config, "version": version}
    try:
        with TraceDelegate(logdir):
            user_task = suite.get_user_task_by_id(case["user_task"])
            if case["injection_task"] is None:
                utility, security = run_task_without_injection_tasks(suite, pipeline, user_task, logdir, True, version)
            else:
                u, s = run_task_with_injection_tasks(suite, pipeline, user_task, attacks[case["suite"]], logdir, True,
                                                     [case["injection_task"]], version)
                utility, security = u[(user_task.ID, case["injection_task"])], s[(user_task.ID, case["injection_task"])]
        row.update(utility=bool(utility), security=bool(security), error=None)
    except Exception as e:  # recorded, not dropped; the case can be retried
        row.update(utility=None, security=None, error=f"{type(e).__name__}: {e}"[:500], trace=traceback.format_exc()[-1500:])
    finally:
        REGISTRY.close(sid)
        P.set_context(None)
    row.update(seconds=round(time.perf_counter() - t0, 2), llm_calls=ctx.llm_calls, tool_calls=ctx.tool_calls,
               prompt_tokens=ctx.prompt_tokens, completion_tokens=ctx.completion_tokens,
               llm_seconds=round(ctx.llm_seconds, 2), tool_seconds=round(ctx.tool_seconds, 2),
               interventions=ctx.interventions)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_id", choices=["P0", "P1", "P2"])
    ap.add_argument("--config", choices=A.CONFIGS, required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-errors", action="store_true")
    a = ap.parse_args()

    version, cases = load_sample(a.pass_id)
    if a.limit:
        cases = cases[:a.limit]
    os.makedirs(A.RESULTS_DIR, exist_ok=True)
    out = os.path.join(A.RESULTS_DIR, f"{a.pass_id}__{a.config}.jsonl")
    done = {}
    if os.path.exists(out):
        for line in open(out):
            r = json.loads(line)
            done[r["key"]] = r
    todo = [c for c in cases if case_key(c) not in done or (a.retry_errors and done[case_key(c)]["error"])]
    logdir = Path(A.RESULTS_DIR) / a.pass_id / a.config

    serve(A.MCP_BIND, A.MCP_PORT)
    pipelines = {s: P.build_pipeline(a.config, s) for s in {c["suite"] for c in cases}}
    attacks = {s: load_attack(A.ATTACK, get_suite(version, s), pipelines[s]) for s in pipelines}
    print(f"{a.pass_id} {a.config} ({version}): {len(todo)} to run, {len(cases) - len(todo)} done, {a.workers} in parallel", flush=True)

    t0, n, tally = time.time(), 0, {"utility": 0, "attacks_won": 0, "errors": 0, "interventions": 0}

    def one(c):
        nonlocal n
        row = run_case(c, a.config, version, logdir, pipelines, attacks)
        with lock:
            with open(out, "a") as f:
                f.write(json.dumps(row) + "\n")
            n += 1
            tally["utility"] += bool(row["utility"])
            tally["attacks_won"] += bool(row["injection_task"] and row["security"])
            tally["errors"] += bool(row["error"])
            tally["interventions"] += len(row["interventions"])
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} {time.time() - t0:.0f}s {tally}", flush=True)
            if row["error"]:
                print(f"    error {row['key']}: {row['error'][:200]}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    print(f"done in {time.time() - t0:.0f}s: {tally}", flush=True)


if __name__ == "__main__":
    main()
