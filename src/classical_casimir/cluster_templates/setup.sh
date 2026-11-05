#!/bin/bash -l
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
policy init-setup
mkdir -p logs
[[ ! -L logs/setup.log && ! -e logs/setup.log ]] || { echo 'Use a fresh setup log'; exit 2; }
echo "Existing-environment check log: $bundle_dir/logs/setup.log"
exec > logs/setup.log 2>&1
load_miniforge
[[ -x "$CASIMIR_ENV/bin/python" ]] || { echo "Existing bempp Python is missing: $CASIMIR_ENV/bin/python"; exit 2; }
conda activate "$CASIMIR_ENV"
"$CASIMIR_ENV/bin/python" -I -B verify-environment.py --inspect
mkdir -p source
tar -xzf source.tar.gz -C source --no-same-owner
"$CASIMIR_ENV/bin/python" -I -B verify-environment.py --record
echo "Using existing environment: $CASIMIR_ENV"
echo 'Application source staged on BIGWORK. Run the scheduled smoke job next.'
