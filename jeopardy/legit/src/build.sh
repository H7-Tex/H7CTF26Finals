#!/usr/bin/env bash
# build + strip the keymaster handout. run from src/.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
out="$here/../keymaster"
python3 "$here/gen.py"
gcc -O2 -fno-stack-protector -o "$out" "$here/keymaster.c"
strip -s "$out"
echo "built: $out"
file "$out"
