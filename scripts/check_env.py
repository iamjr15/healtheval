#!/usr/bin/env python3
"""Validate optional local environment settings."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse


REQUIRED = {
    "SARVAM_API_KEY": "Sarvam panel models",
    "ANTHROPIC_API_KEY": "Claude panel model and judge",
    "GOOGLE_API_KEY": "Gemini panel model and judge",
}

BUDGET_KEYS = {
    "BUDGET_CENTS_PER_DAY_SARVAM_CONVERSATIONS",
    "BUDGET_CENTS_PER_DAY_SARVAM_105B",
    "BUDGET_CENTS_PER_DAY_CLAUDE_SONNET_46",
    "BUDGET_CENTS_PER_DAY_GEMINI_25_PRO",
}

PLACEHOLDER_MARKERS = (
    "REPLACE_ME",
    "CHANGE_ME",
    "YOUR_",
    "INSERT_",
    "PASTE_",
    "<",
    ">",
)


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    key_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: expected KEY=value")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key_re.match(key):
            raise ValueError(f"{path}:{lineno}: invalid key name {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value

    return values


def _is_placeholder(value: str) -> bool:
    upper = value.upper()
    return not value or any(marker in upper for marker in PLACEHOLDER_MARKERS)


def main(argv: list[str]) -> int:
    require_keys = "--require-keys" in argv
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    path = Path(positional[0]) if positional else Path(".env")
    if not path.exists():
        message = (
            ".env is missing. The saved dashboard still runs, but live API "
            "features stay disabled until keys are provided."
        )
        if require_keys:
            print(
                "Environment check failed: " + message + "\n\n"
                "Create it from the template, then replace every placeholder:\n"
                "  cp .env.example .env\n"
                "  $EDITOR .env",
                file=sys.stderr,
            )
            return 1
        print("Environment check warning: " + message)
        return 0

    try:
        values = _parse_env(path)
    except ValueError as exc:
        print(f"Environment check failed: {exc}", file=sys.stderr)
        return 1

    values.setdefault("GOOGLE_API_KEY", values.get("GEMINI_API_KEY", ""))
    errors: list[str] = []
    warnings: list[str] = []
    for key, purpose in REQUIRED.items():
        if key not in values:
            target = errors if require_keys else warnings
            target.append(f"missing {key} ({purpose})")
        elif _is_placeholder(values[key]):
            target = errors if require_keys else warnings
            target.append(f"{key} is still empty or a placeholder")

    for key in BUDGET_KEYS & values.keys():
        value = values[key]
        if value and not _is_placeholder(value) and not value.isdigit():
            errors.append(f"{key} must be a non-negative integer number of cents")

    cerai_url = values.get("CERAI_BASE_URL", "")
    if cerai_url and not _is_placeholder(cerai_url):
        parsed = urlparse(cerai_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("CERAI_BASE_URL must be a full http(s) URL")

    if errors:
        print("Environment check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print("\nFix .env and rerun the Docker command.", file=sys.stderr)
        return 1

    if warnings:
        print("Environment check warning: live API keys are incomplete.")
        for warning in warnings:
            print(f"  - {warning}")
        print("Saved dashboard pages will run; Live Demo stays disabled.")
    else:
        print(f"Environment check passed: {len(REQUIRED)} provider keys found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
