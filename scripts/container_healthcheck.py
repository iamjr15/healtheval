"""Check Streamlit process health without third-party HTTP dependencies."""
from urllib.request import urlopen

from container_entrypoint import port

with urlopen(f"http://127.0.0.1:{port()}/_stcore/health", timeout=3) as response:
    if response.status != 200 or response.read().strip() != b"ok":
        raise SystemExit(1)
