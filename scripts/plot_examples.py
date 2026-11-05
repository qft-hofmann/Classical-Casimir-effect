"""Render the published distance illustration from verified data; no BEM solves."""
import argparse
import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from check_examples import check, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination",type=Path,default=ROOT/"examples/dirichlet-ka1")
    args = parser.parse_args()
    check()
    with (ROOT/"examples/dirichlet-ka1/forces.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    gaps = [float(r["gap_over_a"]) for r in rows]
    forces = [float(r["separation_force"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7.2,4.2),layout="constrained")
    ax.axhline(0,color="0.55",linewidth=.7)
    ax.plot(gaps,forces,"o-",color="#1e5396",markersize=2.5,linewidth=.8,
            label=r"Dirichlet, $ka=1$, $h/a\simeq0.164647$"+"\n150 samples; fixed mesh")
    ax.set(xlabel=r"Surface gap $g/a$",ylabel=r"Helmholtz separation force $F_{\mathrm{sep}}$",
           title="Two spheres under transverse plane-wave illumination")
    ax.legend(frameon=False,fontsize=9,loc="upper right")
    args.destination.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.destination/"force.png",dpi=180)
    plt.close(fig)
    print(args.destination/"force.png")


if __name__ == "__main__":
    main()
