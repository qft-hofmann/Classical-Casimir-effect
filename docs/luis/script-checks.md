# LUIS rules translated into script checks

Audit date: **2026-10-27**. Scope and chapter inventory:
[docs-coverage.md](docs-coverage.md). This is project policy derived from
official sources, not a certificate issued by LUIS. Recheck live documentation and
cluster configuration before each new campaign.

**A** = automatically enforced in the generated bundle; **M** = an operator
responsibility listed for reference; **C** = conditional rule, currently not used. **P** marks a stricter
project choice, including recommendations made mandatory for this project.
At the user's request (2026-10-29), there are no yes/no attestations or module
selection prompts. M entries are not script gates and are not automatically
certified. `operator-review.json` retains its historical name but records runtime
configuration only. Automatic path, environment, Slurm, smoke and accounting
checks remain enforced.

## Storage and output paths

Source: [File systems](https://docs.cluster.uni-hannover.de/doku.php/guide/storage_systems).

| ID | Required check | Enforcement |
|---|---|---|
| FS01 | BIGWORK/HOME are set, absolute, existing and disjoint; check SOFTWARE likewise when set. | A/P |
| FS02 | Canonical bundle, inputs, results and logs lie below BIGWORK. Reject HOME/PROJECT aliases. | A |
| FS03 | New environments belong below SOFTWARE; never store results there. This workflow creates none and reuses the selected legacy HOME environment read-only. | A/P; existing-location exception |
| FS04 | Redirect temporary, Python/JIT, plotting and XDG paths before tools run. | A/P |
| FS05 | Reject output symlinks, escaped paths and linked task artifacts. | A/P |
| FS06 | Check stdout/stderr destinations before submission; shell bodies execute too late. | A/P |
| FS07 | Keep bundles private unless sharing permissions are deliberately reviewed; do not chmod the reused installation. | A/P |
| FS08 | Review byte/inode quotas, soft/hard limits, grace and projected headroom. | M |
| FS09 | Back up essential data independently; BIGWORK, PROJECT and SOFTWARE lack backup. | M |
| FS10 | PROJECT staging occurs on login/transfer nodes. | M |
| FS11 | Node-local TMPDIR is private, capacity checked, ephemeral; copy retained results out. | C |

This bundle chooses BIGWORK for all job temporary data. It does not use node-local
scratch. HOME is left intact; scripts do not edit startup files or create storage
symlink shortcuts. At the user's explicit request (2026-10-29), the already existing
`$HOME/.conda/envs/bempp` is reused without installation or modification. This is
an exception to the project's SOFTWARE placement rule, not a claim that HOME is
the documented installation target. New application source is staged in BIGWORK;
all runtime/package-cache settings and environment records also point there.

## Filesystem load, transfer and deletion

Sources: [Large datasets](https://docs.cluster.uni-hannover.de/doku.php/guide/handling_large_datasets),
[mpiFileUtils](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/mpifileutils),
[Transfers](https://docs.cluster.uni-hannover.de/doku.php/guide/transferring_data),
[Rclone](https://docs.cluster.uni-hannover.de/doku.php/guide/cloud_storage_rclone),
[Archive](https://docs.cluster.uni-hannover.de/doku.php/guide/transferring_files_into_the_archive).

| ID | Required check | Enforcement |
|---|---|---|
| IO01 | Avoid huge small-file collections and repeated whole-tree scans. Pack datasets; use local scratch/overlays when required. | A/P, M |
| IO02 | Reuse the existing dependency tree rather than copying it to Lustre; per-job temporary files are cleaned. | A |
| IO03 | Estimate inode growth and retain only useful files. | M |
| IO04 | Tune Lustre striping only for measured large-file/parallel-I/O needs; moving does not restripe. | C |
| IO05 | Transfer through the transfer host; never submit there. | M, A |
| IO06 | Use resumable transfers and archives for many files; verify checksums and LF scripts. | M, A/P |
| IO07 | Treat sync/delete as destructive: check endpoint, scope, trailing slash and a dry run. | C/P |
| IO08 | Archive access requires registration and suitable bundled files; verify retrieval before deleting originals. | C |
| IO09 | Protect Rclone credentials; distinguish copy from sync; use approved reachable storage. | C |

No transfer, archive, sync/delete or backup is performed automatically. Temporary
cleanup is restricted to a directory created with `mktemp` by that worker. Locks
and integrity checks supplement the scientific result-resumption checks.

## Host, network and account boundaries

Sources: [Connecting](https://docs.cluster.uni-hannover.de/doku.php/guide/connecting_to_cluster),
[Quick start](https://docs.cluster.uni-hannover.de/doku.php/guide/about_the_cluster_system),
[Hardware](https://docs.cluster.uni-hannover.de/doku.php/resources/computing_hardware),
[IT usage rules](https://www.luis.uni-hannover.de/it-compliance-und-zugaenge/it-compliance-luh/nutzungsregelungen).

| ID | Required check | Enforcement |
|---|---|---|
| HOST01 | Real computation, heavy pre/postprocessing and large builds require Slurm allocation. | A, M |
| HOST02 | Bootstrap, preflight and submission require local `login<number>` node name; reject transfer/compute hosts without depending on reverse-DNS domain. | A |
| HOST03 | Query the explicit array element; require one matching job/array record, RUNNING state, this UID and the requested resources. | A |
| NET01 | No compute-node downloads, package installs or dependency on public internet. | A |
| NET02 | University network/VPN and verified SSH host identity are prerequisites. | M |
| ACCOUNT01 | Personal authorized account, research/teaching purpose, no shared credentials. | M |
| ACCOUNT02 | No root/system changes, limit evasion or interference with other users. | A/P, M |
| ACCOUNT03 | Follow security, privacy, copyright and license obligations; report abuse. | M |

The login CPU limit is a protective limit, never a computation allowance. Binary
dependency download and modest installation are permitted setup operations; a
source dependency that requires a substantial build must be handled separately.
Network exceptions require LUIS approval; scripts must not invent workarounds.

## Scheduler and resource requests

Source: [Slurm guide](https://docs.cluster.uni-hannover.de/doku.php/guide/slurm_usage_guide).

| ID | Required check | Enforcement |
|---|---|---|
| JOB01 | Explicit nodes, tasks, CPUs, memory and walltime; omit partition by default so LUIS selects eligible pools. | A/P |
| JOB02 | One node/task for this shared-memory CPU workload. | A |
| JOB03 | Match threads to allocation; cap nested BLAS; reject CPU expansion. | A/P |
| JOB04 | Launch computation with srun; propagate failures; wait for child work. | A/P |
| JOB05 | Array ≤300 elements, indices <1,000,000; concurrency managed by Slurm. | A |
| JOB06 | Slurm enforces live submitted/running/CPU limits; propagate submission rejections. | A (Slurm) |
| JOB07 | Save current association/QoS/partition reports; Slurm checks feasibility and enforces applicable policy. | A |
| JOB08 | No queue flooding, busy polling, automatic retries or duplicate writers. | A/P |
| JOB09 | Use shared CPU resources; no exclusive/GPU request for this solver. | A/P |
| JOB10 | Smoke first; one bounded distance sweep stops for review. Representative pilots/scaling precede a larger campaign. | A/P, M |
| JOB11 | Inspect completed accounting, memory, runtime and CPU use; revise requests. | M |
| JOB12 | Set critical environment inside the batch job. | A |

The default is one fixed-resolution, 150-gap Dirichlet ka=1 curve through g/a=20 after smoke,
without new convergence checks, followed by collection/plotting and a stop.
All 150 cases are submitted as one array without a `%N` throttle. The command line
selects gap range/count, boundary, ka, direction, mesh, quadrature and solver settings.
Each curve holds all parameters except separation fixed; larger sample counts are
split into arrays of at most 300 elements, with subsequent arrays waiting for completion.
The saved parameter record and source identify each run. There is no
concurrency prompt or client-side check of other jobs' queue/CPU usage: Slurm
handles admission, account/QoS limits and concurrency. The submitter propagates
scheduler rejections and does not retry them automatically.
The optional 2,660-case campaign has nine arrays and requires explicit selection.
Each subsequent array waits for completion. The Git entry script checks progress
at one-minute intervals for its own jobs; its bootstrap uses only the standard
library. The wrapper invokes `sbatch --test-only` and leaves admission to Slurm.
An explicit partition is optional in the LUIS docs, not a compliance requirement.
The default omits it, allowing the cluster to select eligible pools (including
`mpp.share` for jobs up to 48 hours). No GPU or exclusive-node resources are requested.
Accounting queries use a bounded 12-week window. For the optional larger campaign,
changed pilot resource/partition profiles require fresh pilot jobs; timings never
come from cached production work.

## Software environments and reproducibility

Sources: [Conda](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/miniforge3),
[Modules/builds/EasyBuild](https://docs.cluster.uni-hannover.de/doku.php/guide/modules_and_application_software),
[uv](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/uv).

| ID | Required check | Enforcement |
|---|---|---|
| ENV01 | Load the cluster-default Miniforge3 automatically, record/reuse its resolved version, and purge mixed module stacks. | A/P |
| ENV02 | Avoid Miniconda/defaults for new installs; the current workflow downloads no packages. | C |
| ENV03 | Reuse the selected existing prefix; disable HOME registration/notices and redirect cache settings to BIGWORK. New installation requires a separately reviewed SOFTWARE/cache configuration. | A/P, C |
| ENV04 | No conda init, automatic profile activation or startup-file mutation. | A |
| ENV05 | No package installation or environment mutation in this workflow; Conda first/pip last applies to future installs. | A, C |
| ENV06 | Disable user-site/config target overrides; use isolated Python and frozen BIGWORK source. | A/P |
| ENV07 | Check Python 3.12 and the observed dependency profile; record actual interpreter/package versions in BIGWORK and reject drift. | A/P |
| ENV08 | Use generic Numba targeting; test binaries/BEM/JIT in the compute-node smoke job and propagate later runtime failures. | A/P |
| ENV09 | Record immutable source/manifest/lock/script hashes; reject changed bundles. | A/P |
| ENV10 | Heavy native builds use allocated matching hardware; review toolchain compatibility. | C |
| ENV11 | Override EasyBuild installation/repository defaults away from HOME. | C/P |
| ENV12 | uv needs an existing Python/virtual environment with explicit SOFTWARE/cache paths. | C |

The project uses generic Numba CPU targeting and the existing dependencies; the smoke
checks the allocated node, not every CPU model that Slurm may later select.
Workers check pinned runtime versions and actual allocations for each job. The
verification profile records nine runtime distributions, not every transitive
package or binary hash. The original Conda metadata remains in the untouched
environment; this profile alone cannot recreate an identical binary installation.
CPU compatibility is checked by execution. No manual authorization, quota, backup,
CPU-compatibility or scheduling-policy attestations gate the workflow.
Conda's cache lists merge across configuration sources. No create/download command
is used here. Any future installer must check effective cache configuration before
creating an explicit SOFTWARE prefix; an environment variable alone is not proof
that HOME fallback caches are excluded.

## Conditional checks for other workload types

These are hard requirements **if the corresponding workflow is added**. They are
not silently declared passed for the current CPU/BEM campaign.

| ID | Workload and required checks | Source |
|---|---|---|
| C01 | MPI/hybrid: consistent MPI/toolchain, rank/thread placement, node topology and transport; use supported modern MPP toolchains (2022+), preferably current. | [Slurm](https://docs.cluster.uni-hannover.de/doku.php/guide/slurm_usage_guide) |
| C02 | GPU: allocate GPUs explicitly; verify device visibility, accelerator memory and actual use. Avoid unnecessary type constraints. | [FAQ](https://docs.cluster.uni-hannover.de/doku.php/guide/cluster_faq) |
| C03 | Apptainer: image only in BIGWORK/SOFTWARE/local tmp; redirect cache/temp and review binds. Fakeroot requires authorization; writable sandboxes needing fakeroot belong locally. | [Apptainer](https://docs.cluster.uni-hannover.de/doku.php/guide/apptainer) |
| C04 | High-I/O containers: use genuinely overlay-backed internal paths; capacity-check overlay; never share one writable overlay between concurrent jobs. | [Apptainer](https://docs.cluster.uni-hannover.de/doku.php/guide/apptainer) |
| C05 | Abaqus: eligible academic license/group, token availability, scratch and CPU/host mapping; unset SLURM_GTIDS where instructed. | [Abaqus](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/abaqus) |
| C06 | ANSYS/CFX: map SMP/MPI resources correctly; license wait behavior, platform/library and fabric settings must match the selected version/nodes. | [ANSYS](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/ansys) |
| C07 | COMSOL: license/group authorization; explicit memory, temporary/recovery paths or disable recovery; test single-node scaling first. | [COMSOL](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/comsol) |
| C08 | Gaussian: authorized license/group and conditions/citations; currently restrict to Intel CPUs. | [Gaussian](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/gaussian), [FAQ](https://docs.cluster.uni-hannover.de/doku.php/guide/cluster_faq) |
| C09 | CPMD: license/group eligibility, correct pseudopotentials, MPI resource layout. | [CPMD](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/cpmd) |
| C10 | FEKO: app-specific CPU-binding workaround only when needed. | [FEKO](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/feko) |
| C11 | MATLAB: licensed single-node parallel toolbox, workers × threads within CPUs, unique job storage, compatible MEX builds. | [MATLAB](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/matlab) |
| C12 | LIGGGHTS: matching MPI build/launcher/rank allocation. | [LIGGGHTS](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/liggghts) |
| C13 | NFFT/MEX: matching MATLAB/FFTW/toolchain and CPU architecture; adapt old installation paths. | [NFFT](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/nfft) |
| C14 | Jupyter/Code-Server: scheduled OOD session, environment compatibility, private tokens/tunnels, end idle sessions; no VS Code server on login. | [Jupyter](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/jupyterlab), [Code-Server](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/code-server) |
| C15 | Visualization: scheduled service, only one session/user, ≤3h, ≤8 CPUs/32GB per documented service; verify hardware rendering. | [Visualization](https://docs.cluster.uni-hannover.de/doku.php/guide/remote_visualization) |
| C16 | Teaching JupyterHub: registered non-critical course, correct account roles/env paths, course dates and resource limits; never use for exams or research. | [JupyterHub](https://docs.cluster.uni-hannover.de/doku.php/resources/jhub) |

## Operational obligations and unresolved external checks

| ID | Required operator check | Source |
|---|---|---|
| OPS01 | Check current outages/maintenance and Cluster-News before long work. | [Status](https://docs.cluster.uni-hannover.de/doku.php/status/system_status), [Quick start](https://docs.cluster.uni-hannover.de/doku.php/guide/about_the_cluster_system) |
| OPS02 | Support reports include username, job IDs, host, paths, timestamps, commands, quota and logs; preserve reproducer. Never send passwords. | [Support](https://docs.cluster.uni-hannover.de/doku.php/guide/how_to_get_support) |
| OPS03 | Use institutional mail; no automatic freemail forwarding or per-task mail flood. Bundle sends no mail. | [FAQ](https://docs.cluster.uni-hannover.de/doku.php/guide/cluster_faq) |
| OPS04 | Verify AI support answers against authoritative docs; never use them as authorization. | [LUHKI](https://docs.cluster.uni-hannover.de/doku.php/resources/luhki_hpc) |
| OPS05 | Record used partitions and applicable funding acknowledgement at publication. | [Citation](https://docs.cluster.uni-hannover.de/doku.php/guide/citation) |
| OPS06 | Verify backups, clean obsolete data/software deliberately, arrange account removal with project management when leaving. | [End of work](https://docs.cluster.uni-hannover.de/doku.php/guide/when_your_work_is_done) |

## Conflicts resolved conservatively

- Slurm wiki: 800 CPUs/user; introductory slides and service description: 768.
  Wiki/slides: 500 submitted tasks; service page: 2,000. These are published general
  values; actual account/QoS limits are enforced by Slurm. The scripts do not
  duplicate those limits or reject work based on a queue snapshot. The published
  general running-job limit is 64; individual accounts may differ. Arrays remain
  at most 300 elements each.
  Sources: [Slurm](https://docs.cluster.uni-hannover.de/doku.php/guide/slurm_usage_guide),
  [slides](https://docs.cluster.uni-hannover.de/lib/exe/fetch.php/course/20260122_luis_cluster_intro.pdf),
  [service](https://www.luis.uni-hannover.de/services/computing/scientific-computing).
- Generic maximum walltime examples do not override partition/QoS limits; MPP
  has a 48-hour limit. Project ceiling is four hours pending measurement.
- HOME installs/build paths in old modules/Jupyter/slides examples conflict with
  the explicit storage chapter. New installations use SOFTWARE and work uses
  BIGWORK. The existing HOME runtime is reused read-only by explicit user choice,
  as recorded above; the workflow does not move it or install anything there.
- FAQ says OOD upload limit 8 GB; slides say 10 GB. Use command-line transfer for
  large data, conservatively above 8 GB.
- Old MPI/toolchain and partition examples are illustrative, not current permission
  to use unsupported combinations. Query live configuration and test the exact job.
- `squeue --array` expands array elements; do not confuse the documentation's short
  option example with `--all`. Queue snapshots race with other clients: Slurm is
  authoritative, and the wrapper does not claim an atomic user-wide reservation.

The script checks assume genuine cluster-provided storage variables, normal user
ownership, and no concurrent hostile path replacement. They are accidental-misuse
guards, not an OS sandbox. Arbitrary third-party plugins, shell startup hooks and
future code changes require a fresh audit. Unknown quota output is **not** guessed
to be safe: the report is saved/displayed without a claim that headroom was certified.
