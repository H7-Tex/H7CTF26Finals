#!/usr/bin/env python3
import sys
from pathlib import Path

from model_a import ModelAError, read_json, volume_policy_document, write_json


def main():
    if len(sys.argv) != 3:
        print("usage: write-volume-policy.py RELEASE OUTPUT", file=sys.stderr)
        return 2
    try:
        release = read_json(Path(sys.argv[1]))
        output = Path(sys.argv[2])
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(output, volume_policy_document(release), 0o600)
    except (ModelAError, OSError) as error:
        print(f"volume policy generation refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
