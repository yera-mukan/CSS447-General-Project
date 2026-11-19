#!/usr/bin/env bash
# Save the full VPA object (including status.recommendation) at the end of a run.
# Usage: scripts/vpa-snapshot.sh <output.json>
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh

OUT="${1:-vpa.json}"
mkdir -p "$(dirname "$OUT")"

if kubectl -n "$NAMESPACE" get vpa ocr >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" get vpa ocr -o json > "$OUT"
  echo "[vpa] wrote $OUT"
else
  echo '{"note":"no VPA object in namespace"}' > "$OUT"
  echo "[vpa] no VPA object, wrote placeholder $OUT"
fi
