#!/usr/bin/env bash
# Stage 5 calibration: one pod, no autoscalers, stepwise concurrent requests.
# Prerequisites:
#   kubectl -n ocr-lab port-forward svc/ocr 18884:8884 &
#   kubectl -n monitoring port-forward svc/prometheus-operated 19090:9090 &
# Usage: VUS_LIST="1 2 4 8 12 16" DURATION=60s bash scripts/calibrate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${TARGET:-http://127.0.0.1:18884}"
PROM_URL="${PROM_URL:-http://127.0.0.1:19090}"
VUS_LIST="${VUS_LIST:-1 2 4 8 12 16}"
DURATION="${DURATION:-60s}"
OUT_DIR="${OUT_DIR:-results/calibration}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

promq() {
  curl -fsS --get "$PROM_URL/api/v1/query" --data-urlencode "query=$1" \
    | jq -r '.data.result[0].value[1] // empty'
}

echo "vus,requests,rps,err_rate,p50_ms,p95_ms,p99_ms,cpu_avg_cores,cpu_max_cores,mem_avg_bytes,mem_max_bytes" \
  > "$OUT_DIR/calibration.csv"

for vus in $VUS_LIST; do
  step_json="$OUT_DIR/k6-vus-$vus.json"
  echo "=== VUS=$vus DURATION=$DURATION"
  ( cd load && TARGET="$TARGET" VUS="$vus" DURATION="$DURATION" STEP="vus-$vus" \
      k6 run --summary-export="$step_json" calibrate.js >/dev/null )

  # Give Prometheus one scrape interval to record the last samples.
  sleep 5

  # Subqueries over the last 90s: average and peak of the per-pod totals.
  cpu_q='sum(rate(container_cpu_usage_seconds_total{namespace="ocr-lab",container="ocr"}[1m]))'
  mem_q='sum(container_memory_working_set_bytes{namespace="ocr-lab",container="ocr"})'
  cpu_avg=$(promq "avg_over_time(($cpu_q)[90s:15s])")
  cpu_max=$(promq "max_over_time(($cpu_q)[90s:15s])")
  mem_avg=$(promq "avg_over_time(($mem_q)[90s:15s])")
  mem_max=$(promq "max_over_time(($mem_q)[90s:15s])")

  python3 - "$step_json" "$vus" "$cpu_avg" "$cpu_max" "$mem_avg" "$mem_max" "$OUT_DIR" <<'PY'
import json, sys
path, vus, cpu_avg, cpu_max, mem_avg, mem_max, out = sys.argv[1:]
d = json.load(open(path))
m = d["metrics"]
reqs = m["http_reqs"]["count"]
rate = m["http_reqs"]["rate"]
err = m["http_req_failed"].get("value", 0)
dur = m["http_req_duration"]
p50 = dur.get("med", 0)
p95 = dur.get("p(95)", 0)
p99 = dur.get("p(99)", 0)
row = f'{vus},{reqs:.0f},{rate:.3f},{err:.4f},{p50:.1f},{p95:.1f},{p99:.1f},{cpu_avg},{cpu_max},{mem_avg},{mem_max}'
print(row)
with open(f"{out}/calibration.csv", "a") as f:
    f.write(row + "\n")
PY
done

echo "Wrote $OUT_DIR/calibration.csv"
column -s, -t "$OUT_DIR/calibration.csv" 2>/dev/null || cat "$OUT_DIR/calibration.csv"
