#!/bin/bash -l
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
policy login
policy init
mkdir -p preflight
checkquota > preflight/quota.txt
clusterinfo -n > preflight/hardware.txt
scontrol show partition > preflight/partitions.txt
scontrol show config > preflight/slurm-config.txt
sacctmgr -n -P show assoc where "user=$(id -un)" > preflight/associations.txt
sacctmgr -n -P show qos > preflight/qos.txt
module -t avail Miniforge3 > preflight/miniforge.txt 2>&1
date -u +%FT%TZ > preflight/checked-utc.txt
echo "Preflight reports saved in $bundle_dir/preflight."
