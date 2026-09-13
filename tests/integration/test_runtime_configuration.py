"""Deployment contracts that can fail before the application renders a page."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.container_entrypoint import port


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_container_rejects_invalid_port(monkeypatch, value):
    monkeypatch.setenv("PORT", value)
    with pytest.raises(ValueError, match="PORT must be"):
        port()


def test_container_uses_platform_port(monkeypatch):
    monkeypatch.setenv("PORT", "8099")
    assert port() == 8099


def test_state_directory_override_is_separate_from_evidence(tmp_path):
    target = tmp_path / "runtime"
    environment = {**os.environ, "HEALTHEVAL_STATE_DIR": str(target)}
    result = subprocess.run(
        [sys.executable, "-c",
         "from streamlit_app.config import STATE_DIR, RESULTS_DIR, PATH_BUDGET_TODAY_JSONL; "
         "assert STATE_DIR != RESULTS_DIR; assert PATH_BUDGET_TODAY_JSONL.parent == STATE_DIR; print(STATE_DIR)"],
        env=environment, capture_output=True, text=True, check=True,
    )
    assert Path(result.stdout.strip()) == target


def test_dotenv_limits_load_before_configuration_and_process_environment_wins(tmp_path):
    # Import a copy with a synthetic .env; never read or replace the developer's keys.
    import streamlit_app.config as config

    package = tmp_path / "test_config"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "config.py").write_text(Path(config.__file__).read_text())
    (tmp_path / ".env").write_text("DAILY_BUDGET_USD=1.75\nLIVE_DEMO_RATE_LIMIT_PER_SESSION=9\n")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(Path.cwd())]),
                   "LIVE_DEMO_RATE_LIMIT_PER_SESSION": "3"}
    environment.pop("DAILY_BUDGET_USD", None)
    subprocess.run(
        [sys.executable, "-c",
         "from test_config.config import DAILY_BUDGET_USD, RATE_LIMIT_PER_SESSION; "
         "assert DAILY_BUDGET_USD == 1.75; assert RATE_LIMIT_PER_SESSION == 3"],
        env=environment, check=True,
    )
