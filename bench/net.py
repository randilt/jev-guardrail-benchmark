"""Median TCP + TLS connect time from this machine to each hosted service -> results/net.json.

Latency to hosted guardrails depends heavily on where you run from; report this next to the latency numbers.

  python -m bench.net
"""
import json, os, socket, ssl, statistics, time
from urllib.parse import urlparse

from bench import config as C


def connect_time(host, n=7):
    ctx = ssl.create_default_context()
    times = []
    for _ in range(n):
        t = time.perf_counter()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                times.append(time.perf_counter() - t)
    return statistics.median(times)


def main():
    hosts = {"Jev": urlparse(C.JEV_BASE_URL).hostname}
    try:
        hosts["Azure Content Safety"] = urlparse(C.azure_cs_endpoint()).hostname
    except SystemExit:
        pass
    judge_host = C.JUDGE_UPSTREAM_HOST
    if not judge_host:
        try:
            h = urlparse(C.judge_url()).hostname
            judge_host = None if h in ("localhost", "127.0.0.1") else h
        except SystemExit:
            pass
    if judge_host:
        hosts["LLM judge"] = judge_host
    res = {name: connect_time(h) for name, h in hosts.items()}
    os.makedirs(C.RESULTS_DIR, exist_ok=True)
    json.dump(res, open(os.path.join(C.RESULTS_DIR, "net.json"), "w"), indent=1)
    print({k: f"{v * 1000:.0f} ms" for k, v in res.items()})


if __name__ == "__main__":
    main()
