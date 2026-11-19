#!/usr/bin/env python3
"""Build the cross-scenario comparison table from results/<scenario>-<rep>/.

Reads summary.json, k6.json, cost.json, vpa.json and pods.txt. Writes
results/comparison.csv and results/comparison.md.
"""
import csv
import glob
import json
import os
import re


def k6(path):
    try:
        m = json.load(open(path))["metrics"]
        reqs = m["http_reqs"].get("count", 0)
        failed = m["http_req_failed"].get("value", 0)
        dur = m["http_req_duration"]
        return {
            "requests": reqs,
            "rps": m["http_reqs"].get("rate", 0),
            "errors_pct": failed * 100,
            "p95_ms": dur.get("p(95)", 0),
            "avg_ms": dur.get("avg", 0),
        }
    except Exception:
        return {}


def vpa_target(path):
    try:
        d = json.load(open(path))
        recs = d["status"]["recommendation"]["containerRecommendations"]
        for r in recs:
            if r.get("containerName") == "ocr":
                return r["target"].get("cpu", ""), r["target"].get("memory", "")
    except Exception:
        pass
    return "", ""


def restarts(path):
    try:
        total = 0
        for line in open(path):
            parts = line.split()
            if len(parts) >= 4 and not parts[0].startswith("NAME"):
                try:
                    total += int(parts[3])
                except ValueError:
                    pass
        return total
    except Exception:
        return ""


rows = []
for summ in sorted(glob.glob("results/*/summary.json")):
    d = os.path.dirname(summ)
    s = json.load(open(summ))
    c = {}
    try:
        c = json.load(open(f"{d}/cost.json"))
    except Exception:
        pass
    k = k6(f"{d}/k6.json")
    cpu_t, mem_t = vpa_target(f"{d}/vpa.json")
    rows.append({
        "scenario": s["scenario"],
        "rep": s["rep"],
        "duration_min": round(s["duration_s"] / 60, 1),
        "requests": round(k.get("requests", 0)),
        "rps": round(k.get("rps", 0), 3),
        "errors_pct": round(k.get("errors_pct", 0), 2),
        "p95_ms": round(k.get("p95_ms", 0)),
        "avg_ms": round(k.get("avg_ms", 0)),
        "replicas_avg": round(c.get("replicas_avg", 0), 2),
        "replicas_max": round(c.get("replicas_max", 0)),
        "pending_max": round(c.get("pending_pods_max", 0)),
        "restarts": restarts(f"{d}/pods.txt"),
        "node_cost": round(c.get("node_cost_usd", 0), 4),
        "alloc_cost": round(c.get("allocated_cost_usd", 0), 4),
        "idle_cost": round(c.get("idle_cost_usd", 0), 4),
        "cost_per_1k": (round(c["cost_per_1k_requests_usd"], 4)
                         if c.get("cost_per_1k_requests_usd") is not None else ""),
        "vpa_cpu_target": cpu_t,
        "vpa_mem_target": mem_t,
        "k6_exit": s.get("k6_exit_code", ""),
    })

os.makedirs("results", exist_ok=True)
fieldnames = list(rows[0].keys()) if rows else []
with open("results/comparison.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)

cols = ["scenario", "rep", "p95_ms", "errors_pct", "rps", "replicas_avg",
        "replicas_max", "pending_max", "restarts", "alloc_cost", "idle_cost",
        "cost_per_1k", "vpa_cpu_target", "vpa_mem_target"]
with open("results/comparison.md", "w") as f:
    f.write("# Scenario comparison (raw runs)\n\n")
    f.write("| " + " | ".join(cols) + " |\n")
    f.write("|" + "|".join(["---"] * len(cols)) + "|\n")
    for r in rows:
        f.write("| " + " | ".join(str(r[c]) for c in cols) + " |\n")

    # Mean +/- range per scenario (only meaningful with >1 repetition).
    f.write("\n## Aggregated per scenario (mean, min..max)\n\n")
    f.write("| scenario | reps | p95 mean | p95 range | errors mean % | alloc_cost mean |\n")
    f.write("|---|---|---|---|---|---|\n")
    scen = sorted({r["scenario"] for r in rows})
    for sc in scen:
        rs = [r for r in rows if r["scenario"] == sc]
        p = [r["p95_ms"] for r in rs]
        e = [r["errors_pct"] for r in rs]
        a = [r["alloc_cost"] for r in rs]
        f.write(f"| {sc} | {len(rs)} | {sum(p)/len(p):.0f} | "
                f"{min(p)}..{max(p)} | {sum(e)/len(e):.2f} | "
                f"{sum(a)/len(a):.4f} |\n")

print(open("results/comparison.md").read())
