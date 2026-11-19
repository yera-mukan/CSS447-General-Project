#!/usr/bin/env python3
"""Stage 8: EC2 cost model for the OCR autoscaling lab.

Formulas (T = run duration in hours, P = node price USD/hour):

    node_cost      = P * T
    cpu_share(t)   = sum(cpu_requests(t)) / NODE_VCPU
    mem_share(t)   = sum(mem_requests(t)) / NODE_RAM
    alloc_share(t) = max(cpu_share, mem_share)      # dominant resource
    allocated_cost = P * integral(alloc_share dt)
    idle_cost      = node_cost - allocated_cost
    cost_per_1k    = allocated_cost / (successful_requests / 1000)
    efficiency     = integral(real_usage dt) / integral(requests dt)

`allocated_cost` models "what the reserved resources would cost if the node
scaled with them"; the real AWS bill for a single node does not depend on the
number of pods.
"""
import argparse
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GIB = 1024 ** 3


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def prom_range(base, query, start, end, step=15):
    params = urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}
    )
    url = f"{base}/api/v1/query_range?{params}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise RuntimeError(f"Prometheus error: {data}")
    return data["data"]["result"]


def series_map(result):
    """Flatten the first series into {unix_ts: float}."""
    if not result:
        return {}
    out = {}
    for ts, val in result[0]["values"]:
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[int(float(ts))] = v
    return out


def integrate(m, t0, t1):
    """Trapezoidal integral over [t0, t1], missing samples count as 0."""
    pts = sorted((int(k), v) for k, v in m.items() if t0 <= int(k) <= t1)
    if not pts:
        return 0.0
    if len(pts) == 1:
        return pts[0][1] * (t1 - t0)
    total = 0.0
    for (ta, va), (tb, vb) in zip(pts, pts[1:]):
        total += (va + vb) / 2.0 * (tb - ta)
    return total


def align_max(a, b, t0, t1):
    """max(a(t), b(t)) sampled on the union of timestamps."""
    keys = sorted({k for k in list(a) + list(b) if t0 <= k <= t1})
    return {k: max(a.get(k, 0.0), b.get(k, 0.0)) for k in keys}


def stats(m):
    vals = list(m.values())
    if not vals:
        return 0.0, 0.0
    return sum(vals) / len(vals), max(vals)


def k6_totals(path):
    try:
        d = json.load(open(path))
        m = d["metrics"]
        reqs = m["http_reqs"].get("count", m["http_reqs"].get("values", {}).get("count", 0))
        failed = m["http_req_failed"].get("value", m["http_req_failed"].get("values", {}).get("rate", 0.0))
        p95 = m["http_req_duration"].get("p(95)", m["http_req_duration"].get("values", {}).get("p(95)", 0.0))
        avg = m["http_req_duration"].get("avg", m["http_req_duration"].get("values", {}).get("avg", 0.0))
        return float(reqs), float(failed), float(p95), float(avg)
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--prom-url", default="http://127.0.0.1:19090")
    ap.add_argument("--k6", required=True)
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--vcpu", type=float, required=True)
    ap.add_argument("--ram-gib", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    t0 = int(parse_ts(a.start).timestamp())
    t1 = int(parse_ts(a.end).timestamp())
    T = max((t1 - t0) / 3600.0, 1e-9)
    ns = 'namespace="ocr-lab",container="ocr"'

    q_cpu_req = f'sum(kube_pod_container_resource_requests{{{ns},resource="cpu"}})'
    q_mem_req = f'sum(kube_pod_container_resource_requests{{{ns},resource="memory"}})'
    q_cpu_use = f'sum(rate(container_cpu_usage_seconds_total{{{ns}}}[2m]))'
    q_mem_use = f'sum(container_memory_working_set_bytes{{{ns}}})'
    q_repl = 'kube_deployment_status_replicas{namespace="ocr-lab",deployment="ocr"}'
    q_pending = 'sum(kube_pod_status_phase{namespace="ocr-lab",phase="Pending"})'

    def get(q):
        return series_map(prom_range(a.prom_url, q, a.start, a.end, 15))

    cpu_req, mem_req = get(q_cpu_req), get(q_mem_req)
    cpu_use, mem_use = get(q_cpu_use), get(q_mem_use)
    repl, pending = get(q_repl), get(q_pending)

    ram_bytes = a.ram_gib * GIB
    cpu_share = {k: v / a.vcpu for k, v in cpu_req.items()}
    mem_share = {k: v / ram_bytes for k, v in mem_req.items()}
    alloc = align_max(cpu_share, mem_share, t0, t1)

    alloc_seconds = integrate(alloc, t0, t1)          # share * seconds
    node_cost = a.price * T
    allocated_cost = a.price * alloc_seconds / 3600.0
    idle_cost = max(node_cost - allocated_cost, 0.0)

    reqs, failed_rate, p95, avg = k6_totals(a.k6)
    successes = max(reqs * (1.0 - failed_rate), 0.0)
    cost_per_1k = allocated_cost / (successes / 1000.0) if successes else None

    cpu_req_int = integrate(cpu_req, t0, t1)
    cpu_use_int = integrate(cpu_use, t0, t1)
    mem_req_int = integrate(mem_req, t0, t1)
    mem_use_int = integrate(mem_use, t0, t1)
    cpu_eff = cpu_use_int / cpu_req_int if cpu_req_int else None
    mem_eff = mem_use_int / mem_req_int if mem_req_int else None

    repl_avg, repl_max = stats(repl)
    pend_avg, pend_max = stats(pending)

    res = {
        "duration_h": T,
        "node_cost_usd": node_cost,
        "allocated_cost_usd": allocated_cost,
        "idle_cost_usd": idle_cost,
        "cpu_share_avg": stats(cpu_share)[0],
        "mem_share_avg": stats(mem_share)[0],
        "requests_total": reqs,
        "successful_requests": successes,
        "error_rate": failed_rate,
        "p95_ms": p95,
        "latency_avg_ms": avg,
        "cost_per_1k_requests_usd": cost_per_1k,
        "cpu_efficiency": cpu_eff,
        "mem_efficiency": mem_eff,
        "replicas_avg": repl_avg,
        "replicas_max": repl_max,
        "pending_pods_avg": pend_avg,
        "pending_pods_max": pend_max,
        "price_per_hour": a.price,
        "vcpu": a.vcpu,
        "ram_gib": a.ram_gib,
        "start": a.start,
        "end": a.end,
    }

    def fmt(v, nd=4):
        return "n/a" if v is None else f"{v:.{nd}f}"

    md = f"""# Cost model — {a.start} .. {a.end}

| Metric | Value |
|---|---|
| Duration | {T * 60:.2f} min ({T:.4f} h) |
| Node price | ${a.price:.5f}/h |
| **node_cost** (real EC2 bill for this node) | **${node_cost:.4f}** |
| **allocated_cost** (reserved resources) | **${allocated_cost:.4f}** |
| idle_cost (paid but not reserved) | ${idle_cost:.4f} |
| avg CPU share of node | {stats(cpu_share)[0] * 100:.1f}% |
| avg RAM share of node | {stats(mem_share)[0] * 100:.1f}% |
| Requests total / successful | {reqs:.0f} / {successes:.0f} |
| Error rate | {failed_rate * 100:.2f}% |
| p95 latency | {p95:.0f} ms |
| **cost per 1k successful requests** | **{('$' + fmt(cost_per_1k, 4)) if cost_per_1k is not None else 'n/a'}** |
| CPU efficiency (usage/requests) | {fmt(cpu_eff, 2)} |
| RAM efficiency (usage/requests) | {fmt(mem_eff, 2)} |
| Replicas avg / max | {repl_avg:.2f} / {repl_max:.0f} |
| Pending pods avg / max | {pend_avg:.2f} / {pend_max:.0f} |

## Notes

- `node_cost` is what AWS charges for the instance; it does **not** change when
  HPA adds pods, because the node is already paid for.
- `allocated_cost` answers "what would the reserved CPU/RAM cost if the node
  size followed the pods". The dominant resource (`max(cpu_share, mem_share)`)
  is used because a pod is limited by whichever resource runs out first.
- Other real bill items not modelled here: EBS volume, public IPv4, egress.
"""
    with open(a.out, "w") as f:
        f.write(md)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
