# Single source of truth for node/app parameters.
# Usage: `source env.sh` in shells, and `include env.sh` in the Makefile.
# Do NOT hardcode these values in Kubernetes manifests.

# Actual instance we could get (c5.xlarge was not available in this account).
# WARNING: only 2 vCPU. This caps how many OCR pods fit on the single node.
export INSTANCE_TYPE="m7i-flex.large"

# Node capacity. `kubectl describe node` reports allocatable cpu=2 and
# memory=7961972Ki (~7.59 GiB) because kubelet reserves a little.
export NODE_VCPU=2
export NODE_RAM_GIB=8

# On-demand Linux price in USD/hour for this instance, provided by the user.
export NODE_PRICE_PER_HOUR=0.10175

# TODO: confirm the AWS region in the console; not used by manifests.
export AWS_REGION="eu-west-1"

export NAMESPACE="ocr-lab"

# Immutable image reference: tag `latest` and commit tag both resolve to this digest.
export OCR_IMAGE="ferraripupu/ocr-app@sha256:3e1fb257348392ad5744aa12dd5af3bc651dbc91060578650bc05f81c7b1b326"

# Pinned versions for reproducibility.
export K3S_VERSION="v1.37.2+k3s1"
export K6_VERSION="v2.4.0"
export HELM_VERSION="v4.3.2"
export VPA_VERSION="1.8.1"
export KPS_CHART_VERSION="93.4.1"

# Load generator (k6 runs on the same host in this lab; see docs/05 notes).
export NODE_PRIVATE_IP="172.31.4.94"
export TARGET_URL="http://127.0.0.1:30884"
