"""Offline publication checks for links, generated inputs and saved evidence.

Only filenames and error categories are printed when sensitive material is found.
This small credential-pattern check complements review; it is not a full secret scanner.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def repository_files() -> list[Path]:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode().split("\0")
    return sorted({ROOT / p for p in paths if p and (ROOT / p).is_file()})


def check_links(paths: list[Path]) -> list[str]:
    errors = []
    for path in paths:
        if path.suffix != ".md":
            continue
        content = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\]\(([^\s()]+)(?:\s+\"[^\"]*\")?\)", content):
            link = urlsplit(target.strip("<>"))
            if link.scheme or link.netloc or not link.path:
                continue
            destination = (path.parent / unquote(link.path)).resolve()
            if not destination.exists():
                errors.append(f"{path.relative_to(ROOT)}: broken local link: {target}")
    return errors


def check_private_files(paths: list[Path]) -> list[str]:
    errors = []
    credential_patterns = {
        "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
        "provider API key": re.compile(r"sk-(?:ant-|sarvam-)[A-Za-z0-9_-]{24,}"),
        "GitHub token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    }
    for path in paths:
        relative = path.relative_to(ROOT)
        if ((path.name.startswith(".env") and path.name != ".env.example")
                or path.name.startswith(".dev.vars") or path.name == "secrets.toml"
                or relative.parts[0] == "var"
                or relative.as_posix().startswith("results/runs/")
                or path.name in {"budget_today.jsonl", "hitl_reviews.jsonl", "threshold_sweeps.jsonl"}):
            errors.append(f"{relative}: private runtime/configuration file must not be published")
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in credential_patterns.items():
            if pattern.search(content):
                errors.append(f"{relative}: possible {label}; inspect locally before publication")
    return errors


def check_generated_assets() -> list[str]:
    from scripts import build_health_assets

    original_root = build_health_assets.ROOT
    errors = []
    with tempfile.TemporaryDirectory(prefix="healtheval-assets-") as temporary:
        target = Path(temporary)
        (target / "data").mkdir()
        shutil.copy2(ROOT / "data/health_case_blueprints.json", target / "data")
        try:
            build_health_assets.ROOT = target
            with contextlib.redirect_stdout(io.StringIO()):
                build_health_assets.main()
        finally:
            build_health_assets.ROOT = original_root
        for generated in target.rglob("*"):
            if generated.is_file():
                relative = generated.relative_to(target)
                published = ROOT / relative
                if not published.exists() or published.read_bytes() != generated.read_bytes():
                    errors.append(f"{relative}: generated asset differs; rebuild and review the benchmark change")
    return errors


def main() -> int:
    paths = repository_files()
    errors = check_links(paths) + check_private_files(paths) + check_generated_assets()
    from streamlit_app.evidence_validator import validate_evidence
    try:
        if validate_evidence() is None:
            errors.append("Published benchmark is absent or incomplete")
    except (OSError, ValueError, RuntimeError) as exc:
        errors.append(f"Published evidence validation failed: {type(exc).__name__}")
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print("Repository checks passed: local documentation links, credential patterns, generated assets and current evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
