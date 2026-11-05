# Optional LUIS workflow

This runner targets the LUIS cluster at Leibniz Universität Hannover. The local
solver and published example plots do not depend on it. The entry point uses
only the system Python standard library until it checks the selected environment.

On a login node, clone below the cluster-provided BIGWORK:

```bash
git clone https://github.com/qft-hofmann/Classical-Casimir-effect.git "$BIGWORK/Classical-Casimir-effect"
cd "$BIGWORK/Classical-Casimir-effect"
bash run-hpc.sh --boundary dirichlet --ka 1 \
  --gap-min 0.1 --gap-max 20 --points 150 --mesh-size 0.2 \
  --cpus 2 --memory-gib 8 --minutes 15
```

For a repository that is still private, use your existing Git authentication.
`--help` lists all options. `--prepare-only` creates a bundle without submission;
`--stop-after smoke` stops after the compute-node smoke test. A normal run proceeds
from smoke to the selected distance curve and collection, then stops for review.

## Site and personal configuration

`configs/luis.json` selects the environment relative to HOME, the Miniforge module
and a requirements file relative to the checkout. The supplied profile uses the
existing `.conda/envs/bempp` environment and the cluster-default `Miniforge3` module.
`requirements-cluster.lock` records the observed runtime versions. These pins are
checked; this workflow never installs or upgrades packages.

To override a setting, create ignored `configs/luis.local.json`, for example:

```json
{"environment_home_relative": ".conda/envs/my-bempp"}
```

Only the three profile keys may be overridden. Environment paths remain within
HOME and requirements paths within the checkout. A custom environment must match
the selected pins. A pinned module can be selected with `miniforge_module`, such
as `Miniforge3/<available-version>`; leaving `Miniforge3` selects the cluster default.

The resolved profile and requirement pins are frozen in each new bundle, hashed
and included in its identity. Saved runs keep their original settings, even if a
local profile subsequently changes. Keep local overrides, credentials and logs
out of Git.

## Numerical and resource choices

Defaults are Dirichlet, ka = 1, transverse illumination, 150 equally spaced gaps
from 0.1 to 20, mesh level 3 and quadrature orders 6/6. `--mesh-size 0.2` selects
h/a ≈ 0.164647; it is mutually exclusive with `--mesh-level`. See the
[mesh table](../usage.md). Requested and attained mesh sizes are recorded.

Use `--direction X Y Z`, `--regular-order`, `--singular-order`, `--rtol` and
`--maxiter` for other numerical parameters. `--steps` aliases `--points`.
CPU, memory and time defaults are 2, 8 GiB and 45 minutes per task. Resource flags
skip value prompts. There are no yes/no or module-selection prompts.

All samples in an array are submitted together without a concurrency throttle;
Slurm controls scheduling and eligible nodes. Curves above 300 points use
successive arrays of at most 300 tasks. The controller monitors only its own jobs
once per minute. The separate `--full-survey` option explicitly selects the older
large campaign; it is never chosen automatically.

## Storage and resumption

New source, results, logs, staging and caches stay below BIGWORK. The environment
is read-only. Compute-node smoke tests exercise the selected runtime; Slurm and
runtime guards check allocations. See the [script checks](script-checks.md) and
[documentation reading record](docs-coverage.md) for site-specific details.

Repeat the same command after a disconnect. After a code update, resume an
existing run with:

```bash
bash run-hpc.sh --resume-run hpc-runs/<saved-run>
```

For a diagnosed task failure, add `--retry-failed`. Successful indices are kept;
only failed indices are submitted again. `--exclude <node>` is an optional
run-specific placement override. `--configure` refreshes resource configuration.
`--recover-array` remains available for saved runs affected by the historical
array-allocation guard issue; it verifies the known failure before repair.

Inspect `collected/summary.csv`, `figures/separation-forces.png` and
`study-review.json`. Completion verifies execution and artifacts; it does not
supply a convergence estimate. Keep important results backed up outside temporary
cluster storage. Operator records and generated `hpc-runs/` are ignored by Git.
