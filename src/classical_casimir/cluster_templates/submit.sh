#!/bin/bash -l
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# -ge 1 && $# -le 3 ]] || { echo 'Usage: bash submit.sh smoke|postprocess|pilot TASK|study BATCH|campaign BATCH [--dry-run]'; exit 2; }
mode="$1"; shift
args=(submit --mode "$mode")
if [[ $mode != smoke && $mode != postprocess ]]; then args+=(--index "${1:?task or batch index required}"); shift; fi
if [[ $# == 1 && $1 == --dry-run ]]; then args+=(--dry-run); shift; fi
[[ $# == 0 ]] || { echo 'Unknown arguments'; exit 2; }
policy "${args[@]}"
