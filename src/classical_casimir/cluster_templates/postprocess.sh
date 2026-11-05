#!/bin/bash -l
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 1 && ( $1 == collect || $1 == plot ) ]] || { echo 'Usage: bash postprocess.sh collect|plot (in a one-node, one-task Slurm allocation)'; exit 2; }
policy interactive
policy init
load_miniforge
conda activate "$CASIMIR_ENV"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1
destination=collected
[[ $1 != plot ]] || destination=figures
"$CASIMIR_ENV/bin/python" -I -B verify-environment.py
exec srun --overlap --nodes=1 --ntasks=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" \
    "$CASIMIR_ENV/bin/python" -I -B "$bundle_dir/run-project.py" "$1" --manifest "$bundle_dir/manifest.json" \
    --output "$bundle_dir/results" --destination "$bundle_dir/$destination"
