"""Reproducible HealthEval preflight without historical result assumptions."""
import argparse
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-keys', action='store_true')
    parser.add_argument('--with-findings', '--require-evidence', dest='require_evidence', action='store_true')
    args = parser.parse_args()
    checks = [[sys.executable, 'scripts/check_env.py', '.env'] + (['--require-keys'] if args.with_keys else []),
              [sys.executable, '-m', 'pytest', 'tests', 'streamlit_app/tests', '-q']]
    if (ROOT / 'node_modules').exists():
        checks.append(['npm', 'run', 'test:worker'])
    for command in checks:
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    from streamlit_app.evidence_validator import validate_evidence
    selected = validate_evidence()
    if args.require_evidence and selected is None:
        print('No completed current-benchmark evidence. Run scripts/run_panel_refset_eval.py and scripts/compute_panel_tool_meta.py.')
        return 1
    print('HealthEval preflight passed. ' + ('Current evidence validated.' if selected else 'No measured benchmark required for this offline check.'))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
