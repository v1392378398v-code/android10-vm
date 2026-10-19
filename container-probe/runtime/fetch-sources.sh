#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/runtime"
OUT="$ROOT/artifacts/container/runtime"
for tool in curl tar sha256sum; do command -v "$tool" >/dev/null; done
mkdir -p "$OUT/downloads" "$OUT/upstream"
while read -r repository commit subtree; do
    name=$(printf '%s' "$repository-$commit-$subtree" | tr / _)
    archive="$OUT/downloads/$name.tar.gz"
    destination="$OUT/upstream/$repository/$subtree"
    if [ ! -d "$destination" ]; then
        if [ ! -s "$archive" ]; then
            curl --fail --silent --show-error --max-time 60 --retry 1 --retry-delay 20 \
                "https://android.googlesource.com/platform/$repository/+archive/$commit/$subtree.tar.gz" \
                -o "$archive.part"
            mv "$archive.part" "$archive"
        fi
        mkdir -p "$destination"
        tar -xzf "$archive" -C "$destination"
    fi
done < "$SRC/archives.txt"
if [ "${1:-}" != --record ]; then
    (cd "$OUT/upstream" && sha256sum --check --status "$SRC/sources.sha256")
fi
