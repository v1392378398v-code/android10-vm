#include "ProbeOutput.h"
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#define _REALLY_INCLUDE_SYS__SYSTEM_PROPERTIES_H_
#include <sys/_system_properties.h>

static int preinit_length;
static char preinit_sdk[PROP_VALUE_MAX];
static int constructor_length;
static char constructor_sdk[PROP_VALUE_MAX];
static int order;
static __thread int initial_tls = 29;
static bool tls_initialized;

static int sdk(char* value) {
    return __system_property_get("ro.build.version.sdk", value);
}

static void preinit() {
    preinit_length = sdk(preinit_sdk);
    tls_initialized = initial_tls == 29;
    if (tls_initialized) order = 1;
}
__attribute__((section(".preinit_array"), used))
static void (*preinit_entry)() = preinit;

__attribute__((constructor)) static void init() {
    constructor_length = sdk(constructor_sdk);
    if (order == 1) order = 2;
}

__attribute__((destructor)) static void fini() {
    emit("fini_complete=%d\n", order == 3);
}

int main(int argc, char** argv) {
    if (argc != 3) return 64;
    pid_t parent = getppid();
    if (parent == 1 || prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != parent) return 70;
    bool reader = strcmp(argv[1], "reader") == 0;
    bool negative = strcmp(argv[1], "missing") == 0 || strcmp(argv[1], "relative") == 0 ||
                    strcmp(argv[1], "incomplete") == 0;
    if (!reader && !negative) return 64;
    bool passed = check(order == 2 && tls_initialized, "bootstrap_init_order");
    char value[PROP_VALUE_MAX] = {};
    int length = sdk(value);
    emit("bootstrap_mode=%s\npreinit_sdk=%s\nconstructor_sdk=%s\nmain_sdk=%s\n",
         argv[1], preinit_sdk, constructor_sdk, value);
    if (reader) {
        passed &= check(preinit_length == 2 && strcmp(preinit_sdk, "29") == 0,
                        "bootstrap_preinit_sdk29");
        passed &= check(constructor_length == 2 && strcmp(constructor_sdk, "29") == 0 &&
                        length == 2 && strcmp(value, "29") == 0, "bootstrap_constructor_sdk29");
        errno = EDOM;
        passed &= check(__system_properties_init() == 0 && errno == EDOM,
                        "bootstrap_property_reinit_errno");
    } else {
        passed &= check(preinit_length == 0 && constructor_length == 0 && length == 0,
                        "bootstrap_no_host_property_fallback");
        uint32_t serial = 0xdeadbeef;
        timespec timeout{};
        passed &= check(__system_properties_init() == -1 &&
                        !__system_property_wait(nullptr, 0, &serial, &timeout) &&
                        serial == 0xdeadbeef, "bootstrap_uninitialized_wait");
    }
    passed &= threadChecks();
    passed &= printIdentity(argv[2]);
    // Keep bytes buffered until the real Bionic exit cleanup runs.
    static char exit_buffer[128];
    passed &= check(setvbuf(stdout, exit_buffer, _IOFBF, sizeof(exit_buffer)) == 0 &&
                    fputs("stdio_flush_complete=1\n", stdout) >= 0, "bootstrap_stdio_buffered");
    order = 3;
    emit("bootstrap_complete=%d\n", passed);
    return passed ? 0 : 1;
}
