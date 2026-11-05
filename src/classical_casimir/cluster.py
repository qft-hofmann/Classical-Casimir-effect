"""Source bundle and Slurm preparation; never logs in or submits jobs."""
from pathlib import Path
from .cluster_templates.bundle import prepare as _prepare, survey_manifest, distance_study_manifest


def prepare(manifest, destination, project_root=None):
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    return _prepare(manifest, destination, root)
