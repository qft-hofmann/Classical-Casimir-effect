#!/bin/bash
# Source this file; do not use inherited Python/Conda target/cache settings.
set -euo pipefail
umask 077
bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -L)"
policy() { /usr/bin/python3 -I -B "$bundle_dir/policy.py" "$@" --bundle "$bundle_dir"; }
load_miniforge() {
    local selected
    selected="$(policy module)"
    module purge
    module load "$selected"
    [[ ${LOADEDMODULES:-} =~ ^Miniforge3/[A-Za-z0-9_.+-]+$ ]] || { echo 'Only Miniforge3 may be loaded'; return 2; }
    [[ $selected == Miniforge3 || $LOADEDMODULES == "$selected" ]] || { echo 'Unexpected Miniforge3 module'; return 2; }
}
settings="$(policy env)"  # fails before mkdir, extraction, package tools or sbatch
eval "$settings"
unset settings
cd -- "$CASIMIR_BUNDLE"
