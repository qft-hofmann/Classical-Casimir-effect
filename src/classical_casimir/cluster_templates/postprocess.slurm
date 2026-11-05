#!/bin/bash -l
#SBATCH --output=/dev/null
#SBATCH --error=/dev/null
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
set -euo pipefail
[[ ${CASIMIR_SUBMIT_MODE:-} == postprocess ]] || exit 2
cd -- "${SLURM_SUBMIT_DIR:?submit with submit.sh}"
bash postprocess.sh collect
exec bash postprocess.sh plot
