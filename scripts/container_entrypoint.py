"""Start the workbench directly with a validated platform-provided port."""
from __future__ import annotations

import os
import sys


def port() -> int:
    try:
        value = int(os.getenv("PORT", "8080"))
    except ValueError as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc
    if not 1 <= value <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return value


def main() -> None:
    args = [
        "streamlit", "run", "/app/streamlit_app/app.py",
        f"--server.port={port()}",
        "--server.address=0.0.0.0",
        "--server.enableXsrfProtection=true",
        "--server.enableCORS=true",
        *sys.argv[1:],
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
