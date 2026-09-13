"""Cache the primary pages in the researched health source manifest."""
from pathlib import Path
import hashlib
import json
import httpx
import yaml
ROOT = Path(__file__).resolve().parents[1]

def main():
    sources = yaml.safe_load((ROOT / "corpus/health_source_manifest.yaml").read_text())["sources"]
    target = ROOT / "corpus/cache"
    target.mkdir(exist_ok=True)
    records = []
    for source in sources:
        try:
            response = httpx.get(source["url"], follow_redirects=True, timeout=30)
            response.raise_for_status()
            path = target / (source["id"].lower() + ".html")
            path.write_bytes(response.content)
            records.append({"id": source["id"], "url": str(response.url), "sha256": hashlib.sha256(response.content).hexdigest()})
        except httpx.HTTPError as exc:
            records.append({"id": source["id"], "error": type(exc).__name__})
    (target / "manifest.json").write_text(json.dumps(records, indent=2))
    failed = sum("error" in r for r in records)
    print(f"Cached {len(records)-failed}/{len(records)} primary sources. See corpus/cache/manifest.json.")
    return bool(failed)

if __name__ == "__main__":
    raise SystemExit(main())
