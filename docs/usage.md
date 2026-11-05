# Local computation

Start with `configs/example.yaml`. Set `boundary` to `dirichlet` or `neumann`,
`k` to the wavenumber, `gap` to the surface gap and `refinement` to the sphere
mesh level. The example uses radius a = 1, incident amplitude A = 1 and direction
(0, 1, 0), transverse to the line joining the sphere centres.

The maximum Euclidean triangle-edge length divided by radius is:

| Refinement | h/a | Triangles/sphere |
|---|---:|---:|
| 0 | 1.051462224 | 20 |
| 1 | 0.618033989 | 80 |
| 2 | 0.324919696 | 320 |
| 3 | 0.164647160 | 1,280 |
| 4 | 0.082603967 | 5,120 |
| 5 | 0.041337256 | 20,480 |
| 6 | 0.020673044 | 81,920 |

Dense assembly memory grows rapidly with mesh refinement. Use the memory estimate
and recorded diagnostics when choosing a resolution. The `--mesh-size` selector
on the optional LUIS runner treats its argument as an upper bound on h/a.
Local case files use the equivalent integer `refinement` value.

```bash
classical-casimir case configs/example.yaml --output output/example
classical-casimir --help
```

Each successful case has a JSON completion record and hashed `arrays.npz` and
`mesh.npz` artifacts. Forces follow the sorted mesh component labels. Repeating
a case resumes only if configuration, source, environment and artifact hashes
match. Failures leave the recorded diagnostics available.

A manifest can be computed using `campaign --manifest FILE --output DIRECTORY`.
The existing distance manifest is `examples/dirichlet-ka1/manifest.json`; the
entire 150-case computation can exceed the local 20-minute budget. Plotting the
published example with `python scripts/plot_examples.py` requires no solves.

For results computed locally, `collect` and `plot` accept `--manifest FILE` and
`--output DIRECTORY` plus an optional `--destination DIRECTORY`. Missing cases
are retained as missing. `validate` runs the longer original pilot; it is not
required to inspect the published data. `survey` and `refine` generate additional
manifests only on explicit request; `prepare` builds a LUIS-specific bundle.
