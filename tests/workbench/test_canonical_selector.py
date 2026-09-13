"""Tests for the canonical panel artefact selector."""

from __future__ import annotations

import json
from pathlib import Path

from streamlit_app.canonical_selector import select_complete_methodology_artifact


def _write_artifact(path: Path, *, done: int, total: int, n_rows: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"prompt_id": f"ref-{i:03d}", "judge_scores": []} for i in range(1, (n_rows or done) + 1)]
    path.write_text(
        json.dumps(
            {
                "n_prompts_done": done,
                "n_prompts_total": total,
                "rows": rows,
            }
        )
    )


def test_returns_complete_panel_artifact(tmp_path: Path) -> None:
    panel = tmp_path / "methodology_panel_refset_eval.json"
    _write_artifact(panel, done=120, total=120)

    chosen = select_complete_methodology_artifact((panel,))

    assert chosen == panel


def test_returns_none_for_incomplete_panel_artifact(tmp_path: Path) -> None:
    panel = tmp_path / "methodology_panel_refset_eval.json"
    _write_artifact(panel, done=42, total=120, n_rows=42)

    chosen = select_complete_methodology_artifact((panel,))

    assert chosen is None


def test_rows_length_mismatch_is_incomplete(tmp_path: Path) -> None:
    panel = tmp_path / "methodology_panel_refset_eval.json"
    _write_artifact(panel, done=120, total=120, n_rows=10)

    chosen = select_complete_methodology_artifact((panel,))

    assert chosen is None


def test_real_repo_panel_artifact_is_complete() -> None:
    chosen = select_complete_methodology_artifact()
    if chosen is not None:
        assert chosen.name == "methodology_panel_refset_eval.json"
