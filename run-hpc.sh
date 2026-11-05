#!/bin/bash -l
# Clone below the cluster-provided BIGWORK, then run this script on a login node.
set -euo pipefail
exec /usr/bin/python3 -I -B "$(dirname -- "${BASH_SOURCE[0]}")/scripts/hpc.py" "$@"
