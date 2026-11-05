# Published numerical examples

These are existing measurements, supplied so the figures can be reproduced
without cluster access or new solver runs.

## Pilot

`pilot/validation.json` is the original local validation record (16 checks),
with Bempp 0.3.1. `budget.json` preserves the elapsed time, memory and completion
status, omitting the personal interpreter command. `source-files.json` records
historical source hashes; numerical kernels match the public code.

Run `python scripts/report_data.py` from the repository root to regenerate the
report's CSV/TeX data. The script accepts `--validation`, `--budget` and
`--destination` for separate datasets. The existing measurements are not rerun.
Historical scope/status strings in the original JSON refer only to the pilot.

## Dirichlet distance curve

`dirichlet-ka1/forces.csv` contains all 150 gaps and both component force vectors.
`separation_force = (F2_x - F1_x)/2`; positive values mean repulsion. These are
Helmholtz forces with a = k = A = 1, not acoustic newtons. The incident direction
is (0,1,0); the spheres lie on the x-axis. The mesh has h/a ≈ 0.164647 and
1,280 triangles per sphere, with regular/singular quadrature orders 6/6.

`samples.json` contains the same values with individual case parameters, software
versions and original result/artifact hashes. `manifest.json` is the computation
recipe. `provenance.json` records export checks and file hashes. All original
case configurations and array/mesh hashes were verified before export. The
original large arrays/meshes and operational logs remain outside this repository.

Run `python scripts/check_examples.py` to verify the published data, then
`python scripts/plot_examples.py` to regenerate `dirichlet-ka1/force.png`.
Lines join adjacent computed samples. The figure illustrates oscillation and
attenuation in these data; it does not fit a decay law or attach a curve-wide
convergence bound. The one-percent sphere benchmark is a separate check.
