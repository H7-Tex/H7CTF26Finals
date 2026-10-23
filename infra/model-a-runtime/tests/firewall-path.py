#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIREWALL = ROOT / "platform/rootfs/usr/local/libexec/finals-platform/firewall"
EXPECTED = "ip daddr 172.31.60.0/24 accept"


def main():
    result = subprocess.run(
        [sys.executable, str(FIREWALL), "--render", "production"],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.split("  chain output {", 1)
    if len(output) != 2 or EXPECTED not in output[1]:
        print(
            "Model A firewall path RED: production output does not allow 172.31.60.0/24",
            file=sys.stderr,
        )
        return 1
    print("Model A firewall path GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
