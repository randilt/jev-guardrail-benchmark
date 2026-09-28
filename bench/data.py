"""Build the benchmark prompt set from pinned public sources.

  python -m bench.data build     download (pinned revisions), check hashes, sample, write data/bench_v1.jsonl
  python -m bench.data verify    check data/bench_v1.jsonl against the committed data/manifest_v1.csv
  python -m bench.data manifest  (maintainers) rewrite data/manifest_v1.csv from data/bench_v1.jsonl

The prompt text itself is not committed. It contains hateful, sexual and self-harm content from the source
datasets. The manifest holds ids, sources, labels and a SHA-256 of each prompt, so a rebuilt set can be
proven identical.
"""
import collections, csv, gzip, hashlib, json, os, random, re, sys, urllib.request

import pyarrow.parquet as pq

from bench import config as C

SEED = 42
HF = "https://huggingface.co/datasets"
SOURCES = {  # file -> (url at a pinned revision, sha256, licence)
    "openai_mod.jsonl.gz": (
        "https://raw.githubusercontent.com/openai/moderation-api-release/f4ab51b5edd3bfbcb349a56324274235b674e0e4/data/samples-1680.jsonl.gz",
        "ef3f7de86ee394fe337b0a566ba4b9c7db058f3caa8d6a4a0006138b663ab9a8", "MIT"),
    "jbb_harmful.csv": (
        f"{HF}/JailbreakBench/JBB-Behaviors/resolve/886acc352a31533ffbcf4ef22c744658688086fc/data/harmful-behaviors.csv",
        "4a8ec6832056b631eb092dccc60d37a61c3d441268268888b3d006288afeffa1", "MIT"),
    "jbb_benign.csv": (
        f"{HF}/JailbreakBench/JBB-Behaviors/resolve/886acc352a31533ffbcf4ef22c744658688086fc/data/benign-behaviors.csv",
        "3cda234d21a991fa309bbfea4b6d9dae31ccdf8e9d452424b6a983e4fdc33468", "MIT"),
    "xstest.csv": (
        f"{HF}/Paul/XSTest/resolve/f600c994b256f12867dfa5b3eb3d545a3e62f8b5/xstest_prompts.csv",
        "11783fb294ed017473ee53c207d71f2161c7672c8d0b037501e78387f801cb5a", "CC-BY-4.0"),
    "itw_jailbreak.parquet": (
        f"{HF}/TrustAIRLab/in-the-wild-jailbreak-prompts/resolve/a10aab8eff1c73165a442d4464dce192bd28b9c5/jailbreak_2023_12_25/train-00000-of-00001.parquet",
        "55bbc5e2be771ee16ed67aed4edb5ecef5f44ac69cea317a67e5405c5c6057a4", "MIT"),
    "itw_regular.parquet": (
        f"{HF}/TrustAIRLab/in-the-wild-jailbreak-prompts/resolve/a10aab8eff1c73165a442d4464dce192bd28b9c5/regular_2023_12_25/train-00000-of-00001.parquet",
        "23e90010ccbc85574bf46678528cddce5b02abc86d9a047209218af65cb37c68", "MIT"),
}

PLAN = {  # bucket -> size
    "jailbreak": 150, "harmful_request": 200, "self_harm": 51, "hate_harassment": 100,
    "sexual": 60, "violence": 36, "benign_lookalike": 350, "benign_real": 150, "benign_unflagged": 100,
}
UNSAFE = {"jailbreak", "harmful_request", "self_harm", "hate_harassment", "sexual", "violence"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download():
    os.makedirs(C.RAW_DIR, exist_ok=True)
    for name, (url, digest, _) in SOURCES.items():
        path = os.path.join(C.RAW_DIR, name)
        if not os.path.exists(path) or sha256_file(path) != digest:
            print(f"downloading {name}")
            urllib.request.urlretrieve(url, path)
        got = sha256_file(path)
        if got != digest:
            raise SystemExit(f"{name}: sha256 {got} does not match the pinned {digest}")
    print(f"all {len(SOURCES)} source files present and verified")


def norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = hashlib.sha1(norm(r["text"]).encode()).hexdigest()
        if key not in seen and r["text"].strip():
            seen.add(key)
            out.append(r)
    return out


def sample(rng, rows, n):
    rows = sorted(rows, key=lambda r: r["source_id"])  # stable before shuffling
    rng.shuffle(rows)
    if len(rows) < n:
        raise SystemExit(f"not enough rows: have {len(rows)}, need {n}")
    return rows[:n]


def openai_primary(r):
    """Multi-label moderation rows get one category, in this order."""
    if r.get("SH") == 1:
        return "self_harm"
    if r.get("S3") == 1 or r.get("S") == 1:
        return "sexual"
    if r.get("H2") == 1 or r.get("H") == 1 or r.get("HR") == 1:
        return "hate_harassment"
    if r.get("V2") == 1 or r.get("V") == 1:
        return "violence"
    return None


def build():
    download()
    rng = random.Random(SEED)
    pools = collections.defaultdict(list)
    raw = C.RAW_DIR

    with gzip.open(os.path.join(raw, "openai_mod.jsonl.gz"), "rt") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            bucket = openai_primary(r) or "benign_unflagged"
            pools[bucket].append({"source": "openai-moderation", "source_id": f"oai-{i}", "text": r["prompt"]})

    for name, bucket in (("jbb_harmful.csv", "harmful_request"), ("jbb_benign.csv", "benign_lookalike")):
        with open(os.path.join(raw, name)) as f:
            for r in csv.DictReader(f):
                pools[bucket + ":jbb"].append({"source": "jailbreakbench", "source_id": f"{name[:-4]}-{r['Index']}",
                                               "text": r["Goal"], "subcategory": r["Category"]})

    with open(os.path.join(raw, "xstest.csv")) as f:
        for r in csv.DictReader(f):
            bucket = "harmful_request:xstest" if r["label"] == "unsafe" else "benign_lookalike:xstest"
            pools[bucket].append({"source": "xstest", "source_id": f"xstest-{r['id']}", "text": r["prompt"],
                                  "subcategory": r["type"]})

    for name, bucket in (("itw_jailbreak.parquet", "jailbreak"), ("itw_regular.parquet", "benign_real")):
        for i, r in enumerate(pq.read_table(os.path.join(raw, name)).to_pylist()):
            text = r["prompt"] or ""
            lo = 200 if bucket == "jailbreak" else 1
            if lo <= len(text) <= 4000:
                pools[bucket].append({"source": "in-the-wild", "source_id": f"{name[:-8]}-{i}", "text": text,
                                      "subcategory": r.get("platform") or ""})

    for k in list(pools):
        pools[k] = dedupe(pools[k])

    picked = []
    picked += [dict(r, bucket="jailbreak") for r in sample(rng, pools["jailbreak"], PLAN["jailbreak"])]
    picked += [dict(r, bucket="harmful_request") for r in sample(rng, pools["harmful_request:jbb"], 100)]
    picked += [dict(r, bucket="harmful_request") for r in sample(rng, pools["harmful_request:xstest"], 100)]
    for b in ("self_harm", "hate_harassment", "sexual", "violence", "benign_unflagged"):
        picked += [dict(r, bucket=b) for r in sample(rng, pools[b], PLAN[b])]
    picked += [dict(r, bucket="benign_lookalike") for r in sample(rng, pools["benign_lookalike:xstest"], 250)]
    picked += [dict(r, bucket="benign_lookalike") for r in sample(rng, pools["benign_lookalike:jbb"], 100)]
    picked += [dict(r, bucket="benign_real") for r in sample(rng, pools["benign_real"], PLAN["benign_real"])]

    # One prompt text must not appear under two buckets.
    by_text = collections.defaultdict(set)
    for r in picked:
        by_text[norm(r["text"])].add(r["bucket"])
    clash = {t for t, b in by_text.items() if len(b) > 1}
    picked = [r for r in picked if norm(r["text"]) not in clash]

    rng.shuffle(picked)
    with open(C.BENCH_FILE, "w") as f:
        for i, r in enumerate(picked):
            row = {"id": f"p{i:04d}", "source": r["source"], "source_id": r["source_id"], "bucket": r["bucket"],
                   "subcategory": r.get("subcategory", ""), "label": "unsafe" if r["bucket"] in UNSAFE else "benign",
                   "text": r["text"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = collections.Counter(r["bucket"] for r in picked)
    print(f"wrote {len(picked)} prompts to {C.BENCH_FILE}")
    for b in PLAN:
        print(f"  {b:18} {counts[b]}")
    verify()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load():
    if not os.path.exists(C.BENCH_FILE):
        raise SystemExit("data/bench_v1.jsonl is missing: run `python -m bench.data build` first")
    return [json.loads(l) for l in open(C.BENCH_FILE)]


def manifest():
    rows = load()
    with open(C.MANIFEST_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "source", "source_id", "bucket", "subcategory", "label", "chars", "sha256"])
        for r in rows:
            w.writerow([r["id"], r["source"], r["source_id"], r["bucket"], r["subcategory"], r["label"],
                        len(r["text"]), text_hash(r["text"])])
    print(f"wrote {C.MANIFEST_FILE} ({len(rows)} rows)")


def verify():
    rows = load()
    with open(C.MANIFEST_FILE) as f:
        want = list(csv.DictReader(f))
    bad = [m["id"] for m, r in zip(want, rows)
           if (m["id"], m["bucket"], m["label"], m["sha256"]) != (r["id"], r["bucket"], r["label"], text_hash(r["text"]))]
    if len(want) != len(rows) or bad:
        raise SystemExit(f"prompt set does NOT match the manifest ({len(rows)} vs {len(want)} rows, "
                         f"{len(bad)} differ, first: {bad[:5]})")
    print(f"prompt set matches the manifest ({len(rows)} prompts)")


if __name__ == "__main__":
    {"build": build, "verify": verify, "manifest": manifest}.get(sys.argv[1] if len(sys.argv) > 1 else "",
                                                                 lambda: print(__doc__))()
