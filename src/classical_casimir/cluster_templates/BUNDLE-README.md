# LUIS campaign bundle — prepared, never submitted by prepare

Read [LUIS-CHECKS.md](LUIS-CHECKS.md) before using this bundle. The complete source
audit and the distinction between automated, operator and conditional checks are
there. Each new run needs its own compute-node smoke test with the existing
Bempp 0.3.2 runtime; the earlier local numerical pilot used 0.3.1.

For the Git checkout, use its top-level `bash run-hpc.sh`: the default is a smoke
job followed by one fixed-resolution distance curve, then a
compute-node collection/plot job and a hard stop for review. It performs no new
convergence runs, isolated-reference solves or force-identity checks. The script
builds this bundle and performs automatic preflight. There are no yes/no
attestations or module-selection prompts. The site profile selects Miniforge3 (the cluster default unless pinned) and records
the resolved version for that run. The resolved profile is frozen in `site-profile.json`.
The current default is 150 equally spaced samples from g/a=0.1 to 20, Dirichlet
at ka=1. Use `--gap-min`, `--gap-max`, `--points`, `--boundary`, `--ka`, `--direction`,
`--mesh-size` (maximum edge h/a), `--mesh-level` (alternative), `--regular-order`, `--singular-order`, `--rtol` and `--maxiter` on
`run-hpc.sh` for another parameter set. Resource flags are `--cpus`, `--memory-gib`
and `--minutes`. `run-parameters.json` records the request; changed parameters
select a new run directory and the same command resumes its own run.
`--mesh-size 0.2` selects the default level 3 mesh with attained h/a ≈ 0.164647
and 1,280 triangles per sphere. A requested bound chooses the coarsest supported
mesh satisfying it. `study_scope` records the requested and attained sizes;
equivalent mesh selections identify the same run. No convergence jobs are added.
The commands below are the lower-level interface for inspecting individual stages.

`bundle.json` / `resource-plan.json` describe the selected scope. The first distance
sweep uses `bash submit.sh study 0`; it needs the successful smoke check and valid
resource configuration, with default ceilings of 2 CPUs, 8 GiB and 45 minutes per calculation.
The default 150 samples use `--array=0-149`, without a concurrency throttle.
Larger requested curves are split into arrays of at most 300 elements and completed
one batch at a time. Slurm manages placement, admission,
account/QoS limits and simultaneous execution. There is no concurrency question
or client-side queue-capacity check.
The broader campaign/pilot procedure below applies only when `--full-survey` has
been explicitly selected after deciding to expand the work.

Copy the whole bundle to a **new, private directory below the cluster-provided
`$BIGWORK`**. Use `transfer.cluster.uni-hannover.de` for transfers and verify the
SSH fingerprint against the official documentation. Preserve Unix LF endings.
Do not redefine BIGWORK/SOFTWARE/HOME to bypass checks or symlink the bundle.
The scripts use the existing environment selected by the frozen profile read-only
(default `$HOME/.conda/envs/bempp`). No environment is created or modified and no packages are installed.
Inputs, staged project source, results, logs, environment records, temporary files
and all runtime caches use BIGWORK. SOFTWARE is optional for this reuse workflow;
HOME and PROJECT are not output targets.

Partition selection defaults to automatic (`"partition": null` in
`operator-review.json`): `submit.sh` omits `--partition` and lets LUIS choose
eligible nodes from explicit CPU, memory and time requests. The LUIS Slurm guide
includes `mpp.share` for unpinned jobs up to 48 hours. No specific node, GPU or exclusive
allocation is requested. A deliberate pin to a documented shared CPU partition
remains supported in the review file; it is not required for this study.

On a login node, from the copied bundle:

```bash
bash preflight.sh
# Reports are saved for diagnostics. Default module/resources are already configured.
bash setup.sh
bash submit.sh smoke --dry-run
bash submit.sh smoke
```

Setup activates the existing environment and checks Python 3.12 and every runtime
version in `requirements-cluster.lock`. This verification profile records the
observed legacy packages: Bempp 0.3.2, NumPy 2.1.3, Numba 0.61.0 and llvmlite 0.44.0,
plus SciPy, meshio, Matplotlib, PyYAML and psutil. It is not an installation step.
Missing or changed packages stop the workflow without attempting a repair.

The frozen application is extracted to `source/src` on BIGWORK and run through
`run-project.py` using the legacy interpreter with `-I -B`. No installed project
distribution is required. The runtime snapshot is `environment.json` in this
bundle and setup output is `logs/setup.log`. Workers check that snapshot and source
hashes. The selected HOME environment, previous partial SOFTWARE environment and
old logs are retained untouched. Future new installations belong in SOFTWARE;
reuse here is an explicit exception for the existing installation's location.

Do not attest CPU compatibility before execution: the compute-node smoke job
tests binaries, BEM and Numba compilation on its allocated node. Workers check
their pinned environment and run the solver on their own nodes, propagating
failures. A smoke pass does not prove compatibility with every other CPU model.
No CPU-compatibility or manual scheduler-policy acknowledgement is required.

After Slurm reports the smoke array element COMPLETED with exit 0:0, inspect
`smoke-results/smoke-check.json`, `smoke-proof.json`, logs and environment records.
Then run representative **actual manifest cases**, including expensive DD/NN cases
at small gaps, high frequency, finest mesh and quadrature settings:

```bash
bash submit.sh pilot GLOBAL_TASK_INDEX
# After each pilot finishes: sacct -j JOB_ID ...; seff JOB_ID
# Review memory, elapsed time, CPU use and scaling on the allocated hardware.
```

Record successful pilot array-element IDs (such as `12345_42`) in
`operator-review.json`; the submitter verifies successful accounting rather than
requiring a yes/no certification. The top-level full-survey workflow records these
IDs automatically and prints efficiency reports. Defaults are **uncalibrated
ceilings per calculation**: one node/task, 2 CPUs, 32 GiB, 4 hours.
The wrapper permits 1–8 CPUs; explicit partition pins are limited to shared CPU pools. It rejects scheduler
CPU expansion caused by a mismatched memory request. Configuration has no
24-hour expiry. Waiting in the scheduler does not invalidate an
already submitted job's pinned environment; workers verify the actual allocation.

```bash
bash submit.sh campaign 0 --dry-run
bash submit.sh campaign 0
# Wait for this batch to finish and inspect accounting/results before batch 1, etc.
```

`bundle.json` lists all batch ranges (at most 300 tasks each). The 2,660-case survey
has nine batches. **One invocation submits one batch only**. Global array indices
map directly to the unchanged manifest, without offsets. The wrapper runs
`sbatch --test-only` before submission and propagates scheduler rejections. It does
not inspect other jobs, reserve queue slots or add an array concurrency throttle.
Scheduler/account/QoS rules govern admission and concurrent execution.
The lower-level submitter has no polling loop or auto-retry. The top-level Git
entry script waits at one-minute intervals and advances one completed batch at a
time; it never queues the entire survey in advance.

Use **submit.sh**, never direct `sbatch campaign.slurm`: the wrapper supplies
absolute log paths and performs storage checks before Slurm opens stdout/stderr.
Direct batch files default to `/dev/null` and refuse work without the wrapper mode.
Do not pass arbitrary sbatch options or edit checked scripts in place: regenerate
the bundle for code changes. `operator-review.json` is intentionally editable;
source, manifest, lock and executable templates are integrity checked.
After a code update, `run-hpc.sh --resume-run RUN --retry-failed` retains a saved
distance study's frozen source/results and resubmits only failed task indices.
`--exclude NODE` excludes a problematic node for that run. Successful samples and
the original smoke proof are retained; retry records survive disconnects.
The Git entry script's `--recover-array RUN` is a narrow exception for the known
old array-ID guard failure: it backs up the allowlisted guard, records and checks
the replacement, retains all scientific source/results and retries only failed
elements before collection/plotting. Use the recovery instructions in the checkout's
`docs/hpc-run.md`; do not hand-edit bundle checksums.

Workers set their own module/thread/cache environment, validate the allocation and
all pinned versions, launch with `srun`, lock the selected task and propagate its
exit status. Temporary files are private to each job and cleaned on normal exit or
failure; a node crash/SIGKILL can leave them for later deliberate cleanup. Cached
results are reused only if source, case, environment and artifact hashes match.
Production and pilots share a task lock. Pilot outputs are separate per job under
`pilot-results/<array-job-id>/`, so changing resources measures a fresh solve.

For collection/plotting use a separate allocated compute session. For example,
on the login node request a modest interactive allocation (adapt to live limits):

```bash
salloc --nodes=1 --ntasks=1 --cpus-per-task=2 --mem=4G --time=00:30:00
# Enter a shell ON the allocated node (salloc alone may leave you on login):
srun --overlap --pty bash -l
# Change to this bundle on BIGWORK, then:
bash postprocess.sh collect
bash postprocess.sh plot
```

Do not run the survey solver or large postprocessing on login nodes. Read
`collected/coverage.json` before plotting; missing results remain missing. Back up
important results off cluster, optionally stage archives via PROJECT from login or
transfer nodes. Neither BIGWORK, SOFTWARE nor PROJECT is backed up by LUIS. Verify
backup checksums before any cleanup; these scripts never delete campaign results.
