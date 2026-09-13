"""Promptfoo adapter using the same health prompt and provider client as the workbench."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from eval.panel_clients import call_panel_model,load_system_prompt

def call_api(prompt, options, context):
    load_dotenv(ROOT/'.env', override=False)
    model_id=(options.get('config') or {}).get('modelId')
    result=call_panel_model(model_id,load_system_prompt(),prompt)
    return {'output':result.response,'metadata':{'model_id':result.model_id}}
