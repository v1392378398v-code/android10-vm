#include "Probe.h"
#include <stdio.h>
#include <string.h>
#include <sys/system_properties.h>
#include <unistd.h>

int main(int argc, char** argv) {
    using namespace hwbinder_probe;
    setvbuf(stdout, nullptr, _IOLBF, 0);
    if (argc != 3) return 2;
    setenv("A10VM_HWBINDER_PATH", argv[2], 1);
    char sdk[PROP_VALUE_MAX]{};
    __system_property_get("ro.build.version.sdk", sdk);
    printf("hwbinder_role=%s\nhwbinder_pid=%d\nhwbinder_uid=%u\nhwbinder_sdk=%s\n",
            argv[1], getpid(), getuid(), sdk);
    if (!strcmp(argv[1], "registry")) return registry();
    if (!strcmp(argv[1], "service")) return service();
    if (!strcmp(argv[1], "client")) return client();
    if (!strcmp(argv[1], "looper")) return looper();
    return 2;
}
