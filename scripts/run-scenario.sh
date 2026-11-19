#!/usr/bin/env bash
# Run one scenario once: reset -> apply overlay -> k6 spike -> snapshots -> cost.
# Usage: scripts/run-scenario.sh <scenario> <rep>
# Example: scripts/run-scenario.sh B-hpa-50 1
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh

SCENARIO="${1:?usage: run-scenario.sh <scenario> <rep>}"
REP="${2:-1}"
OUT="$(pwd)/results/${SCENARIO}-${REP}"
mkdir -p "$OUT"

command -v k6 >/dev/null || { echo "k6 not installed"; exit 1; }

kp() { kubectl -n "$NAMESPACE" "$@"; }

echo "[run] scenario=$SCENARIO rep=$REP -> $OUT"

# 1. Baseline + cooldown.
COOLDOWN="${COOLDOWN:-180}" bash scripts/reset.sh

# 2. Apply the overlay.
kubectl apply -k "k8s/scenarios/$SCENARIO"
kp rollout status deploy/ocr --timeout=300s

# 3. Stable Prometheus access for remote-write (pod does not churn during a run).
if ! curl -fsS -m 2 http://127.0.0.1:19090/-/ready >/dev/null 2>&1; then
  pkill -f 'port-forward svc/prometheus-operated 19090' 2>/dev/null || true
  kubectl -n monitoring port-forward svc/prometheus-operated 19090:9090 \
    >/tmp/opencode/prom-pf.log 2>&1 &
  echo $! > /tmp/opencode/prom-pf.pid
  for i in $(seq 1 20); do
    curl -fsS -m 2 http://127.0.0.1:19090/-/ready >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 4. The load generator uses a NodePort on localhost; it survives pod churn.
for i in $(seq 1 30); do
  curl -fsS -m 2 "$TARGET_URL/.well-known/health/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS -m 3 "$TARGET_URL/.well-known/health/ready" >/dev/null

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date -u +%s)"
echo "[run] start=$START_ISO (epoch $START_EPOCH)"

# 5. Load profile (~10 min). k6 exits 99 when thresholds are crossed; that is a
#    valid experimental result, so do not abort on it.
set +e
(
  cd load
  K6_PROMETHEUS_RW_SERVER_URL=http://127.0.0.1:19090/api/v1/write \
  K6_PROMETHEUS_RW_TREND_STATS='avg,min,max,p(90),p(95),p(99)' \
  TARGET="$TARGET_URL" \
  RUN_SCENARIO="$SCENARIO" \
  k6 run -o experimental-prometheus-rw \
    --tag rep="$REP" --tag scenario="$SCENARIO" \
    --summary-export="$OUT/k6.json" \
    spike.js
) >"$OUT/k6.log" 2>&1
K6_RC=$?
set -e

END_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH="$(date -u +%s)"
echo "[run] end=$END_ISO (epoch $END_EPOCH) k6_rc=$K6_RC"

# 6. Snapshots of the resulting state.
bash scripts/vpa-snapshot.sh "$OUT/vpa.json"
kp get pods -o wide > "$OUT/pods.txt" 2>&1 || true
kp get deploy ocr -o yaml > "$OUT/deployment.yaml" 2>&1 || true
kp get hpa ocr -o yaml > "$OUT/hpa.yaml" 2>&1 || true
kp get vpa ocr -o yaml > "$OUT/vpa.yaml" 2>&1 || true

# 6b. Grafana annotation spanning this run (if Grafana is port-forwarded).
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:13000}"
if curl -fsS -m 2 -u admin:ocrlab "$GRAFANA_URL/api/health" >/dev/null 2>&1; then
  curl -fsS -m 5 -u admin:ocrlab -X POST "$GRAFANA_URL/api/annotations" \
    -H 'Content-Type: application/json' \
    -d "{\"dashboardUID\":\"ocr-autoscaling-lab\",\"time\":$((START_EPOCH*1000)),\"timeEnd\":$((END_EPOCH*1000)),\"tags\":[\"ocr-run\",\"$SCENARIO\"],\"text\":\"$SCENARIO rep $REP\"}" \
    >/dev/null 2>&1 && echo "[run] Grafana annotation created" || true
fi

# 7. Cost model (Stage 8).
if [ -f scripts/cost.py ]; then
  python3 scripts/cost.py \
    --start "$START_ISO" --end "$END_ISO" \
    --prom-url http://127.0.0.1:19090 \
    --k6 "$OUT/k6.json" \
    --price "$NODE_PRICE_PER_HOUR" --vcpu "$NODE_VCPU" --ram-gib "$NODE_RAM_GIB" \
    --out "$OUT/cost.md" > "$OUT/cost.json" 2>"$OUT/cost.err" || \
    echo "[run] cost.py failed, see $OUT/cost.err"
fi

# 8. Machine-readable run summary.
python3 - "$OUT" "$SCENARIO" "$REP" "$START_ISO" "$END_ISO" "$START_EPOCH" "$END_EPOCH" "$K6_RC" <<'PY'
import json, sys
out, scenario, rep, start, end, se, ee, rc = sys.argv[1:]
summary = {
    "scenario": scenario,
    "rep": int(rep),
    "start": start,
    "end": end,
    "start_epoch": int(se),
    "end_epoch": int(ee),
    "duration_s": int(ee) - int(se),
    "k6_exit_code": int(rc),
    "k6": f"{out}/k6.json",
    "vpa": f"{out}/vpa.json",
    "cost": f"{out}/cost.md",
}
json.dump(summary, open(f"{out}/summary.json", "w"), indent=2)
print(json.dumps(summary, indent=2))
PY

echo "[run] done: $OUT"
