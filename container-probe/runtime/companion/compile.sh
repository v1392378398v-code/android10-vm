#!/bin/sh
# Sourced by companion library and behavior-probe builders.
compile() {
    input=$1
    object=$2
    shift 2
    set -- --target=aarch64-linux-android29 -nostdinc \
        -isystem "$UP/external/libcxx/include" \
        -isystem "$UP/external/libcxxabi/include" \
        -isystem "$UP/external/libunwind_llvm/include" \
        -isystem "$(clang -print-resource-dir)/include" \
        -isystem "$B/include" -isystem "$B/kernel/uapi/asm-arm64" \
        -isystem "$B/kernel/uapi" -isystem "$B/kernel/android/uapi" \
        -I"$B" -I"$B/private" \
        -fPIC -fno-stack-protector -fno-emulated-tls -mno-outline-atomics \
        -ffunction-sections -fdata-sections -O2 -U_FORTIFY_SOURCE \
        -MD -MF "$object.d" "$@"
    case "$input" in
        *.cpp|*.cc) python3 "$CACHE" "$object" clang++ \
            -nostdinc++ -std=gnu++14 -fexceptions -frtti -D_USING_LIBCXX "$@" \
            -c "$input" -o "$object" ;;
        *.c) python3 "$CACHE" "$object" clang "$@" -std=gnu99 -c "$input" -o "$object" ;;
        *.S) python3 "$CACHE" "$object" clang "$@" -D__ASSEMBLY__ -c "$input" -o "$object" ;;
        *) printf 'Unsupported source: %s\n' "$input" >&2; exit 1 ;;
    esac
}
