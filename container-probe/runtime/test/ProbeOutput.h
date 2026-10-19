#pragma once
#ifdef A10VM_DYNAMIC_PROBE
#include <stdio.h>
#else
#include <async_safe/log.h>
#endif
#include <errno.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>

inline bool emit(const char* format, ...) {
    char text[2048];
    va_list args;
    va_start(args, format);
#ifdef A10VM_DYNAMIC_PROBE
    int length = vsnprintf(text, sizeof(text), format, args);
#else
    int length = async_safe_format_buffer_va_list(text, sizeof(text), format, args);
#endif
    va_end(args);
    if (length < 0 || static_cast<size_t>(length) >= sizeof(text)) return false;
    const char* cursor = text;
    while (length > 0) {
        ssize_t count = TEMP_FAILURE_RETRY(write(STDOUT_FILENO, cursor, length));
        if (count <= 0) return false;
        cursor += count;
        length -= count;
    }
    return true;
}

inline bool check(bool passed, const char* name) {
    return emit("CHECK\t%s\t%d\n", name, passed) && passed;
}

bool threadChecks();
bool printIdentity(const char* nonce);
