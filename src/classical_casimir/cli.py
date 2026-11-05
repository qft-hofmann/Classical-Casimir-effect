"""Command-line entry point. Cluster preparation never logs in or submits."""
import argparse
import json
import os
from pathlib import Path
import sys
import yaml
from .study import read_manifest, atomic_json, run_case, collect, case_id


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("case", help="run a JSON/YAML case under a local watchdog")
    c.add_argument("config"); c.add_argument("--output", default="output/cases")
    c.add_argument("--seconds", type=float, default=1200)
    for name in ("campaign", "execute"):
        c = sub.add_parser(name, help="budgeted local manifest" if name == "campaign" else argparse.SUPPRESS)
        c.add_argument("--manifest", required=True); c.add_argument("--output", required=True)
        c.add_argument("--seconds", type=float, default=1200)
    c = sub.add_parser("task", help="run a zero-based Slurm array task")
    c.add_argument("--manifest", required=True); c.add_argument("--task-id", type=int, required=True)
    c.add_argument("--output", required=True); c.add_argument("--dry-run", action="store_true")
    c.add_argument("--smoke", action="store_true")
    for name in ("validate", "_validate"):
        c = sub.add_parser(name, help="budgeted local validation" if name == "validate" else argparse.SUPPRESS)
        c.add_argument("--output", default="output/local")
        c.add_argument("--seconds", type=float, default=1200)
    c = sub.add_parser("_case", help=argparse.SUPPRESS)
    c.add_argument("config"); c.add_argument("--output", required=True)
    c = sub.add_parser("survey", help="write the complete cluster manifest")
    c.add_argument("--destination", default="configs/survey.json")
    c = sub.add_parser("prepare", help="create source/environment/Slurm bundle, without submission")
    c.add_argument("--manifest", required=True); c.add_argument("--destination", default="output/cluster")
    c = sub.add_parser("collect", help="verify artifacts and report missing cases")
    c.add_argument("--manifest", required=True); c.add_argument("--output", required=True)
    c.add_argument("--destination", default="output/collected")
    c = sub.add_parser("plot", help="plot collected results, preserving gaps and error status")
    c.add_argument("--manifest", required=True); c.add_argument("--output", required=True)
    c.add_argument("--destination", default="output/figures")
    c = sub.add_parser("refine", help="prepare midpoint cases at empirically resolved sign brackets")
    c.add_argument("--manifest", required=True); c.add_argument("--output", required=True)
    c.add_argument("--destination", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command in ("case", "campaign", "validate"):
        from .budget import run_budgeted
        Path(args.output).mkdir(parents=True, exist_ok=True)
        if args.command == "case":
            command = [sys.executable, "-m", "classical_casimir", "_case", args.config, "--output", args.output]
        elif args.command == "campaign":
            command = [sys.executable, "-m", "classical_casimir", "execute", "--manifest", args.manifest, "--output", args.output]
        else:
            command = [sys.executable, "-m", "classical_casimir", "_validate", "--output", args.output]
        result = run_budgeted(command, Path(args.output)/f"{args.command}.log", seconds=args.seconds)
        print(json.dumps(result, indent=2))
        return 0 if result["returncode"] == 0 else 1
    if args.command == "_case":
        case = yaml.safe_load(Path(args.config).read_text())
        result = run_case(case, args.output)
        print(json.dumps(dict(id=result["id"], forces=result["forces"], seconds=result["seconds"])))
    elif args.command == "execute":
        for case in read_manifest(args.manifest)["cases"]:
            result = run_case(case, args.output)
            print(json.dumps(dict(id=result["id"], seconds=result["seconds"], resumed=result.get("resumed", False))), flush=True)
    elif args.command == "task":
        data = read_manifest(args.manifest)
        if args.task_id < 0 or args.task_id >= len(data["cases"]):
            raise ValueError("task-id is outside the manifest")
        case = data["cases"][args.task_id]
        if args.smoke:
            case = dict(geometry="sphere", boundary="dirichlet", k=1., refinement=1, isolated=False,
                        solver=dict(memory_gib=4.), angular_order=12)
        if args.dry_run:
            print(json.dumps(dict(id=case_id(case), case=case)))
        else:
            if not os.environ.get("SLURM_JOB_ID"):
                raise RuntimeError("task execution requires a Slurm allocation; use campaign for budgeted local runs")
            result = run_case(case, args.output)
            if args.smoke:
                from .analytic import AnalyticSphere
                from .model import PlaneWave
                import numpy as np
                exact = AnalyticSphere(PlaneWave(1.)).boundary_force()
                error = np.linalg.norm(np.asarray(result["forces"])[0]-exact)/np.linalg.norm(exact)
                atomic_json(Path(args.output)/"smoke-check.json", dict(relative_force_error=error, versions=result["versions"], passed=bool(error < .2)))
                if error >= .2: raise RuntimeError("cluster smoke force check failed")
            print(json.dumps(dict(id=result["id"], seconds=result["seconds"])))
    elif args.command == "_validate":
        from .validation import run_validation
        result = run_validation(args.output)
        print(json.dumps(dict(status=result["status"], seconds=result["seconds"])))
        return 0 if result["status"] == "passed" else 1
    elif args.command == "survey":
        from .cluster import survey_manifest
        data = survey_manifest(); atomic_json(args.destination, data)
        print(json.dumps(dict(cases=len(data["cases"]), destination=args.destination)))
    elif args.command == "prepare":
        from .cluster import prepare
        print(json.dumps(prepare(args.manifest, args.destination)))
    elif args.command == "collect":
        print(json.dumps(collect(args.manifest, args.output, args.destination)))
    elif args.command in ("plot", "refine"):
        from .postprocess import plot_results, refinement_manifest
        if args.command == "plot":
            print(json.dumps(plot_results(args.manifest, args.output, args.destination)))
        else:
            data = refinement_manifest(args.manifest, args.output)
            atomic_json(args.destination, data)
            print(json.dumps(dict(cases=len(data["cases"]), destination=args.destination)))
    return 0

