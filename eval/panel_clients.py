"""Direct panel-model clients used by the offline runner and Streamlit demo.

The measured panel is the four API-backed models in ``data/model_panel.yaml``:
Sarvam 105B Conversations, Sarvam 105B, Claude Sonnet 4.6, and Gemini 2.5 Pro.  This module
intentionally does not route through the legacy browser/comparator paths; every
call is a normal vendor API request under the shared HealthEval system prompt.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT_PATH = REPO_ROOT / "data" / "system_prompt_health.yaml"
MODEL_PANEL_PATH = REPO_ROOT / "data" / "model_panel.yaml"

SARVAM_API_MODEL_BY_PANEL_ID: Mapping[str, str] = {
    "sarvam-105b-conversations": "sarvam-105b-conversations",
    "sarvam-105b": "sarvam-105b",
}

PANEL_MODEL_IDS: tuple[str, ...] = (
    "sarvam-105b-conversations",
    "sarvam-105b",
    "claude-sonnet-4-6",
    "gemini-2.5-pro",
)

DEFAULT_LIVE_PANEL_MODEL_ID = "sarvam-105b-conversations"


@dataclass(frozen=True)
class PanelResponse:
    model_id: str
    response: str
    latency_sec: float


def load_system_prompt() -> str:
    """Load the shared Hindi health system prompt from YAML."""
    with SYSTEM_PROMPT_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    prompt = doc.get("system_prompt") or doc.get("prompt") or ""
    if isinstance(prompt, dict):
        prompt = prompt.get("text") or prompt.get("body") or ""
    return str(prompt).strip()


def load_panel_model_ids() -> list[str]:
    """Return API-backed panel ids in YAML order."""
    if not MODEL_PANEL_PATH.exists():
        return list(PANEL_MODEL_IDS)
    with MODEL_PANEL_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    ids: list[str] = []
    for row in doc.get("panel", []) or []:
        model_id = str(row.get("model_id") or "")
        if model_id in PANEL_MODEL_IDS and str(row.get("dispatch_type", "API")) == "API":
            ids.append(model_id)
    return ids or list(PANEL_MODEL_IDS)


def required_env_vars(model_ids: list[str] | tuple[str, ...]) -> set[str]:
    """Return environment variables required for the selected panel models."""
    needed: set[str] = set()
    for model_id in model_ids:
        if model_id.startswith("sarvam-"):
            needed.add("SARVAM_API_KEY")
        elif model_id == "claude-sonnet-4-6":
            needed.add("ANTHROPIC_API_KEY")
        elif model_id == "gemini-2.5-pro":
            needed.add("GOOGLE_API_KEY")
        else:
            raise ValueError(f"Unsupported panel model: {model_id}")
    return needed


def validate_panel_env(model_ids: list[str] | tuple[str, ...]) -> None:
    """Raise when any selected model's required key is absent."""
    missing = sorted(name for name in required_env_vars(model_ids)
                     if not (google_api_key() if name == "GOOGLE_API_KEY" else os.getenv(name)))
    if missing:
        raise RuntimeError(f"Missing required env vars for panel run: {', '.join(missing)}")


def google_api_key() -> str | None:
    """Accept either documented Google SDK environment variable."""
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


def _call_sarvam(model_id: str, system_prompt: str, user_prompt: str) -> str:
    api_model = SARVAM_API_MODEL_BY_PANEL_ID[model_id]
    key = os.environ["SARVAM_API_KEY"]
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={
                "api-subscription-key": key,
                "Content-Type": "application/json",
            },
            json={
                "model": api_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "reasoning_effort": None,
                "max_tokens": 2048,
            },
        )
    resp.raise_for_status()
    payload = resp.json()
    return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )


def _call_google(system_prompt: str, user_prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=google_api_key())
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=512, include_thoughts=False),
            temperature=0.0,
        ),
    )
    return getattr(resp, "text", "") or ""


def model_generation_config(model_id: str) -> dict:
    """Record decoding settings alongside measured responses."""
    settings = {"temperature": 0.0, "max_output_tokens": 2048}
    if model_id.startswith("sarvam-"):
        settings["reasoning_effort"] = None
    elif model_id == "gemini-2.5-pro":
        settings.update(max_output_tokens=4096, thinking_budget=512)
    return settings


def call_panel_model(model_id: str, system_prompt: str, user_prompt: str) -> PanelResponse:
    """Call one configured panel model and return text plus latency."""
    if model_id not in PANEL_MODEL_IDS:
        raise ValueError(f"Unsupported panel model: {model_id}")

    t0 = time.perf_counter()
    if model_id in SARVAM_API_MODEL_BY_PANEL_ID:
        text = _call_sarvam(model_id, system_prompt, user_prompt)
    elif model_id == "claude-sonnet-4-6":
        text = _call_anthropic(system_prompt, user_prompt)
    elif model_id == "gemini-2.5-pro":
        text = _call_google(system_prompt, user_prompt)
    else:  # pragma: no cover - guarded by PANEL_MODEL_IDS above.
        raise ValueError(f"Unsupported panel model: {model_id}")
    return PanelResponse(
        model_id=model_id,
        response=text,
        latency_sec=time.perf_counter() - t0,
    )
