"""Command line entrypoint for manual photo tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hardware_scan.scanner import Scanner, load_catalog


def main() -> None:
    """Scan one local photo and write a compact JSON result to stdout."""
    parser = argparse.ArgumentParser(description="Read a hardware model from a photo")
    parser.add_argument("image", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    arguments = parser.parse_args()
    result = Scanner().scan(arguments.image.read_bytes(), load_catalog(arguments.catalog))
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
