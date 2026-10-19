#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/container-probe/binder"
OUT="$ROOT/artifacts/container/runtime"
MANIFEST=${2:-"$SRC/archives.txt"}
HASHES=${3:-"$SRC/sources.sha256"}
for tool in curl tar sha256sum; do command -v "$tool" >/dev/null; done
mkdir -p "$OUT/downloads" "$OUT/upstream"
while read -r repository commit subtree; do
    name=$(printf '%s' "$repository-$commit-$subtree" | tr / _)
    archive="$OUT/downloads/$name.tar.gz"
    destination="$OUT/upstream/$repository/$subtree"
    marker="$destination/.a10vm-complete-$commit"
    if [ ! -f "$marker" ]; then
        if [ ! -s "$archive" ]; then
        if [ "$subtree" = . ]; then
            url="https://android.googlesource.com/platform/$repository/+archive/$commit.tar.gz"
        else
            url="https://android.googlesource.com/platform/$repository/+archive/$commit/$subtree.tar.gz"
        fi
            curl --fail --silent --show-error --max-time 60 --retry 1 --retry-delay 20 \
                "$url" -o "$archive.part"
            mv "$archive.part" "$archive"
        fi
        mkdir -p "$destination"
        tar -xzf "$archive" -C "$destination"
        touch "$marker"
    fi
done < "$MANIFEST"
if [ "${1:-}" != --record ] && [ -f "$HASHES" ]; then
    (cd "$OUT/upstream" && sha256sum --check --status "$HASHES")
fi
