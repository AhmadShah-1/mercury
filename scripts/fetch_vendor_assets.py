"""Fetch pinned browser assets and verify their published SHA-384 digests."""

from __future__ import annotations

import base64
import hashlib
import urllib.request
from pathlib import Path

ASSETS = {
    "bootstrap.min.css": (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css",
        "sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB",
    ),
    "bootstrap.bundle.min.js": (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js",
        "FKyoEForCGlyvwx9Hj09JcYn3nv7wiPVlz7YYwJrWVcXK/BmnVDxM+D2scQbITxI",
    ),
    "htmx.min.js": (
        "https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js",
        "2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg",
    ),
}


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "mercury" / "static" / "vendor"
    target.mkdir(parents=True, exist_ok=True)
    for filename, (url, expected) in ASSETS.items():
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed HTTPS URLs
            content = response.read()
        actual = base64.b64encode(hashlib.sha384(content).digest()).decode()
        if actual != expected:
            raise RuntimeError(f"integrity check failed for {filename}")
        (target / filename).write_bytes(content)


if __name__ == "__main__":
    main()
