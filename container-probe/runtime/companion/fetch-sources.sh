#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$ROOT/container-probe/runtime/companion"
OUT="$ROOT/artifacts/container/runtime"
for tool in curl tar sha256sum base64; do command -v "$tool" >/dev/null; done
sh "$ROOT/container-probe/runtime/dynamic/fetch-sources.sh"
while read -r repository commit subtree; do
    name=$(printf '%s' "$repository-$commit-$subtree" | tr / _)
    archive="$OUT/downloads/$name.tar.gz"
    destination="$OUT/upstream/$repository/$subtree"
    marker="$destination/.a10vm-complete-$commit"
    if [ ! -f "$marker" ]; then
        if [ ! -s "$archive" ]; then
            case "$subtree" in
                .) url="https://android.googlesource.com/platform/$repository/+archive/$commit.tar.gz" ;;
                *) url="https://android.googlesource.com/platform/$repository/+archive/$commit/$subtree.tar.gz" ;;
            esac
            curl --fail --silent --show-error --max-time 60 --retry 1 --retry-delay 20 \
                "$url" -o "$archive.part"
            tar -tzf "$archive.part" >/dev/null
            mv "$archive.part" "$archive"
        fi
        mkdir -p "$destination"
        tar -xzf "$archive" -C "$destination"
        touch "$marker"
    fi
done < "$SRC/archives.txt"
while read -r repository commit; do
    input="$OUT/upstream/$repository/Android.bp"
    if [ ! -f "$input.a10vm-$commit" ]; then
        curl --fail --silent --show-error --max-time 60 --retry 1 --retry-delay 20 \
            "https://android.googlesource.com/platform/$repository/+/$commit/Android.bp?format=TEXT" \
            -o "$input.base64"
        base64 -d "$input.base64" > "$input.part"
        mv "$input.part" "$input"
        touch "$input.a10vm-$commit"
        rm "$input.base64"
    fi
done <<'BLUEPRINTS'
external/libcxx d356ee1683aa5681564c81ad69fe19bc6abd5da5
external/libcxxabi b599c4d59ebf8d589c82a1d5fd98a6c0a955fe7b
BLUEPRINTS
if [ "${1:-}" != --record ] && [ -f "$SRC/sources.sha256" ]; then
    (cd "$OUT/upstream" && sha256sum --check --status "$SRC/sources.sha256")
fi
