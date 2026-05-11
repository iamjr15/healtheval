#!/usr/bin/env python3
"""Promote approved HITL calibration candidates into the judge-memory YAML."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CANDIDATES = REPO_ROOT / "data" / "judge_calibration_candidates.jsonl"
DEFAULT_OUT = REPO_ROOT / "data" / "judge_calibration_examples.yaml"

# Ledger-only fields must not leak into the retriever pack.
_LEDGER_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "approved_by_human",
        "client_session_id",
        "import_provenance",
    }
)

_YAML_FIELDS: tuple[str, ...] = (
    "id",
    "metric",
    "rubric_version",
    "source",
    "ref_id",
    "prompt",
    "actual_answer",
    "expected_behaviour",
    "human_score",
    "human_reason",
    "failure_category",
    "approved_by",
    "created_at",
)


def _read_candidates(path: Path) -> list[dict[str, Any]]:
    """Parse the JSONL ledger; tolerate trailing partial lines.

    The reader matches ``data_loaders._read_jsonl`` semantics so the
    workbench and this offline tool see the same view of the file.
    """
    if not path.exists():
        raise FileNotFoundError(f"candidates JSONL not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line_num, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                # Surface malformed rows so the maintainer can fix the ledger.
                print(
                    f"WARNING: {path}:{line_num} skipped — JSON decode error: {exc}",
                    file=sys.stderr,
                )
                continue
    return rows


def _filter_approved(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep only rows whose ``approved_by_human`` flag is truthy."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("approved_by_human"):
            out.append(dict(r))
    return out


def _dedupe_by_id(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest row per ``id`` (by ``created_at``, lex-comparable on ISO 8601)."""
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        rid = str(r.get("id", ""))
        if not rid:
            continue
        existing = by_id.get(rid)
        if existing is None:
            by_id[rid] = dict(r)
            continue
        # ISO 8601 timestamps are lexicographically sortable.  Prefer the
        # later created_at; tie-break by file-order (last-wins) which
        # matches HITL append semantics.
        if str(r.get("created_at", "")) >= str(existing.get("created_at", "")):
            by_id[rid] = dict(r)
    return list(by_id.values())


def _strip_to_yaml_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Drop ledger-only audit fields; keep only what the YAML schema declares."""
    out: dict[str, Any] = {}
    for key in _YAML_FIELDS:
        if key in row:
            out[key] = row[key]
    # Defensively scrub any ledger-only keys that accidentally landed in
    # the candidates row (defence in depth — if a future refactor adds
    # one, the YAML still stays clean).
    for k in _LEDGER_ONLY_FIELDS:
        out.pop(k, None)
    return out


def _build_pack(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble the final ``CalibrationPack`` shape — sorted by ``id`` for idempotence."""
    examples = sorted(
        (_strip_to_yaml_fields(r) for r in rows),
        key=lambda e: str(e.get("id", "")),
    )
    return {
        "schema_version": "v1",
        "examples": examples,
    }


def _atomic_write_yaml(pack: Mapping[str, Any], out_path: Path) -> None:
    """Write ``pack`` to ``out_path`` via tmp file + ``os.replace`` for atomicity."""
    import yaml  # lazy

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        # ``allow_unicode=True`` so Devanagari is preserved verbatim;
        # ``sort_keys=False`` so the YAML key order matches our
        # _YAML_FIELDS tuple (deterministic for diff review).
        yaml.safe_dump(
            pack,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=88,
        )
    os.replace(tmp_path, out_path)


def promote(
    candidates_path: Path = DEFAULT_CANDIDATES,
    out_path: Path = DEFAULT_OUT,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote approved candidates from JSONL → YAML.  Returns the resulting pack."""
    rows = _read_candidates(candidates_path)
    approved = _filter_approved(rows)
    deduped = _dedupe_by_id(approved)
    pack = _build_pack(deduped)

    print(
        f"  read    : {len(rows)} candidates from {candidates_path}",
        flush=True,
    )
    print(f"  approved: {len(approved)} (after filter)", flush=True)
    print(f"  emitted : {len(pack['examples'])} (after dedupe by id)", flush=True)

    if dry_run:
        print(f"  --dry-run: would write to {out_path} (no file written)", flush=True)
    else:
        _atomic_write_yaml(pack, out_path)
        print(f"  wrote   : {out_path}", flush=True)

    return pack


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="Path to data/judge_calibration_candidates.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Path to data/judge_calibration_examples.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be written; no file changes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        promote(args.candidates, args.out, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: write failed: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
