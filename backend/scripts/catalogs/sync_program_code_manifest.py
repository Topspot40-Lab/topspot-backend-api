"""Import the approved backend program-code manifest into the catalog tree."""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


CATALOG_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path(r"C:\tmp\topspot-program-code-registry\backend\data\program_code_manifest.json")
DEFAULT_OUTPUT = CATALOG_DIR / "approved_program_code_manifest.json"


def sync(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> str:
    """Copy the approved source verbatim and return its SHA-256 digest."""
    payload = source.read_bytes()
    output.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(sync(args.source, args.output))


if __name__ == "__main__":
    main()
