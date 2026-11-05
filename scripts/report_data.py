"""Export actual pilot values into editable TeX tables and numerical CSV plots."""
from pathlib import Path
import csv
import json
import sys
import argparse

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"src"))
from classical_casimir.cluster_templates.bundle import sphere_mesh_parameters

def mesh_size(row):
    return sphere_mesh_parameters(refinement=row["refinement"])["mesh_size"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--validation", type=Path, default=root/"examples/pilot/validation.json")
parser.add_argument("--budget", type=Path, default=root/"examples/pilot/budget.json")
parser.add_argument("--destination", type=Path, default=root/"reports/data")
args = parser.parse_args()
data = json.loads(args.validation.read_text())
budget = json.loads(args.budget.read_text())
if data["status"] != "passed" or budget["returncode"] != 0:
    raise SystemExit("The pilot must finish successfully before exporting the report")
dest = args.destination; dest.mkdir(parents=True, exist_ok=True)

for bc in ("dirichlet", "neumann"):
    rows = [r for r in data["spheres"] if r["boundary"] == bc]
    with (dest/f"sphere-{bc}.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n"); writer.writerow(["h_over_a", "triangles", "error"])
        writer.writerows((mesh_size(r),r["diagnostics"]["elements"], r["force_relative_error"]) for r in rows)
    rows = [r for r in data["pairs"] if r["boundary"] == bc]
    discrepancies = [r["position_discrepancy"]/abs(r["position"]["force"][0]) for r in rows]
    assert all(b < a for a, b in zip(discrepancies, discrepancies[1:])), "relative force discrepancy did not decrease"
    with (dest/f"identity-{bc}.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n"); writer.writerow(["h_over_a", "triangles", "error"])
        writer.writerows((mesh_size(r),r["diagnostics"]["elements"]//2,
                          r["position_discrepancy"]/abs(r["position"]["force"][0])) for r in rows)

sphere_table = []
for row in data["spheres"]:
    sphere_table.append(f"{'D' if row['boundary']=='dirichlet' else 'N'} & {mesh_size(row):.6f} & {row['diagnostics']['elements']} & {row['force'][1]:.6f} & {100*row['force_relative_error']:.3f} & {100*row['far_field_relative_error']:.3f} & {100*row['near_field_relative_error']:.3f} " + chr(92)*2)
(dest/"sphere-table.tex").write_text("\n".join(sphere_table)+"\n")
pair_table = []
for row in data["pairs"]:
    pair_table.append(f"{'D' if row['boundary']=='dirichlet' else 'N'} & {mesh_size(row):.6f} & {row['diagnostics']['elements']//2} & {row['forces'][1][0]:.6f} & {row['position']['force'][0]:.6f} & {row['position_discrepancy']:.3g} & {row['position']['step_difference'][0]:.2g} " + chr(92)*2)
(dest/"pair-table.tex").write_text("\n".join(pair_table)+"\n")
macros = dict(PilotSeconds=f"{budget['seconds']:.1f}", PeakRSS=f"{budget['peak_rss_gib']:.2f}",
              BackendVersion=data['versions']['bempp-cl'], CheckCount=str(len(data['checks'])),
              SourceDigest=data['source_sha256'][:16],
              ExactD=f"{data['spheres'][0]['exact_force'][1]:.9f}",
              ExactN=f"{next(r for r in data['spheres'] if r['boundary']=='neumann')['exact_force'][1]:.9f}")
(dest/"values.tex").write_text("\n".join(f"\\newcommand{{\\{key}}}{{{value}}}" for key,value in macros.items())+"\n")
(dest/"source.json").write_text(json.dumps(dict(validation="examples/pilot/validation.json" if args.validation == root/"examples/pilot/validation.json" else args.validation.name,
    budget="examples/pilot/budget.json" if args.budget == root/"examples/pilot/budget.json" else args.budget.name, source_sha256=data['source_sha256'],
    mesh_size_definition="h/a = maximum Euclidean triangle-edge length divided by sphere radius",
    mesh_size_annotation="Derived from the unchanged sphere mesh family; no new BEM solves."), indent=2)+"\n")
print('Exported numerical report data')

