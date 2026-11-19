#!/usr/bin/env bash
# Return the lab to the baseline: no HPA/VPA, 1 replica, base requests.
# Waits for the pod to be Ready, then an optional cooldown so that VPA
# recommendations from the previous run do not leak into the next one.
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh

COOLDOWN="${COOLDOWN:-180}"

echo "[reset] removing autoscalers in namespace $NAMESPACE"
kubectl -n "$NAMESPACE" delete hpa ocr --ignore-not-found
kubectl -n "$NAMESPACE" delete vpa ocr --ignore-not-found

echo "[reset] applying k8s/base (1 replica, base requests)"
kubectl apply -k k8s/base >/dev/null
kubectl -n "$NAMESPACE" rollout status deploy/ocr --timeout=300s

echo "[reset] cooldown ${COOLDOWN}s"
sleep "$COOLDOWN"
