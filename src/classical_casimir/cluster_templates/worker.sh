#!/bin/bash -l
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 0 ]] || { echo 'Worker arguments are fixed by submit.sh'; exit 2; }
policy allocation
policy task-check
policy init
load_miniforge
conda activate "$CASIMIR_ENV"
# Each element has private temporary/config/JIT files; retained data stay BIGWORK.
job_tmp="$(mktemp -d "$bundle_dir/runtime/job-${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}.XXXXXX")"
trap 'rm -rf -- "$job_tmp"' EXIT
export TMPDIR="$job_tmp/tmp" TMP="$job_tmp/tmp" TEMP="$job_tmp/tmp"
export XDG_CACHE_HOME="$job_tmp/cache" XDG_CONFIG_HOME="$job_tmp/config"
export XDG_DATA_HOME="$job_tmp/data" XDG_STATE_HOME="$job_tmp/state" XDG_RUNTIME_DIR="$job_tmp/run"
export NUMBA_CACHE_DIR="$job_tmp/numba" MPLCONFIGDIR="$job_tmp/matplotlib"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_RUNTIME_DIR" "$NUMBA_CACHE_DIR" "$MPLCONFIGDIR"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK" NUMBA_NUM_THREADS="$SLURM_CPUS_PER_TASK"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export OMP_MAX_ACTIVE_LEVELS=1 OMP_DYNAMIC=FALSE MKL_DYNAMIC=FALSE
"$CASIMIR_ENV/bin/python" -I -B verify-environment.py
output="$bundle_dir/results"
extra=()
if [[ $CASIMIR_SUBMIT_MODE == smoke ]]; then
    output="$bundle_dir/smoke-results"
    extra=(--smoke)
elif [[ $CASIMIR_SUBMIT_MODE == pilot ]]; then
    # Benchmark again for each pilot job/resource profile; never time a resumed
    # production result as if it were a new computation.
    output="$bundle_dir/pilot-results/${SLURM_ARRAY_JOB_ID}"
fi
# Lock just this task. EXIT releases the descriptor, including on application failure.
mkdir -p "$bundle_dir/locks"
lock_kind=task
[[ $CASIMIR_SUBMIT_MODE != smoke ]] || lock_kind=smoke
exec 8>"$bundle_dir/locks/${lock_kind}-${SLURM_ARRAY_TASK_ID}.lock"
flock -n 8 || { echo 'Duplicate task is already active'; exit 2; }
srun --nodes=1 --ntasks=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" --kill-on-bad-exit=1 \
    "$CASIMIR_ENV/bin/python" -I -B "$bundle_dir/run-project.py" task --manifest "$bundle_dir/manifest.json" \
    --task-id "$SLURM_ARRAY_TASK_ID" --output "$output" "${extra[@]}"
if [[ $CASIMIR_SUBMIT_MODE == smoke ]]; then policy smoke-proof; fi
