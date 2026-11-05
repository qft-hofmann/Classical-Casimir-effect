#!/bin/bash -l
# Direct sbatch is unsupported. submit.sh supplies absolute checked log paths,
# explicit resources and at most 300 array elements; Slurm selects eligible pools.
#SBATCH --output=/dev/null
#SBATCH --error=/dev/null
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
set -euo pipefail
[[ ${CASIMIR_SUBMIT_MODE:-} == campaign || ${CASIMIR_SUBMIT_MODE:-} == pilot || ${CASIMIR_SUBMIT_MODE:-} == study ]] || exit 2
cd -- "${SLURM_SUBMIT_DIR:?submit with submit.sh}"
exec bash worker.sh
