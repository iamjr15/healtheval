"""Bind saved responses and scores to the exact benchmark that produced them."""
from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "healtheval_health_v1"
PROMPT_VERSION = "health_reference_risk_v1"


def benchmark_fingerprint(root: Path = REPO_ROOT) -> str:
    paths = [
        root / "data/reference_set.yaml",
        root / "data/system_prompt_health.yaml",
        root / "data/constitution.yaml",
        root / "data/judge_calibration_examples.yaml",
        *sorted((root / "data/rubrics").glob("*.yaml")),
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def benchmark_metadata() -> dict[str, str]:
    return {
        "dataset_version": DATASET_VERSION,
        "benchmark_fingerprint": benchmark_fingerprint(),
        "reference_review_status": "pending_clinical_review",
    }


def require_current_benchmark(artifact: dict, *, label: str = "artifact") -> None:
    if artifact.get("benchmark_fingerprint") != benchmark_fingerprint():
        raise ValueError(
            f"{label} belongs to a different benchmark. Regenerate it with the "
            "current reference set, system prompt, rubric, and calibration examples."
        )
