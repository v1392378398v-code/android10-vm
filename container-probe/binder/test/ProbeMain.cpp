#include "Probe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>
#include <unistd.h>

namespace probe {
static void exitBuffers() {
    a10binder_buffer_stats stats{};
    a10binder_get_buffer_stats(&stats);
    printf("binder_exit_buffers_alive=1\n");
    fflush(stdout);
}
bool check(const char* name, bool passed) {
    printf("CHECK\t%s\t%d\n", name, passed); fflush(stdout);
    return passed;
}
sp<IBinder> findService() {
    for (int n = 0; n < 100; ++n) {
        sp<IBinder> result = defaultServiceManager()->checkService(String16(kService));
        if (result != nullptr) return result;
        usleep(20000);
    }
    return nullptr;
}
}
int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IOLBF, 0);
    if (argc != 3) return 2;
    setenv("A10VM_BINDER_PATH", argv[2], 1);
    char sdk[PROP_VALUE_MAX]{};
    __system_property_get("ro.build.version.sdk", sdk);
    printf("binder_role=%s\nbinder_pid=%d\nbinder_uid=%u\nbinder_sdk=%s\n", argv[1], getpid(), getuid(), sdk);
    if (!strcmp(argv[1], "buffer-exit")) {
        // A later-initialized buffer store must outlive already-registered Binder cleanup.
        if (atexit(probe::exitBuffers)) return 1;
        a10binder_buffer_stats stats{};
        a10binder_get_buffer_stats(&stats);
        return 0;
    }
    if (!strcmp(argv[1], "inspect")) return probe::resources(argv[2]);
    if (!strcmp(argv[1], "driver-switch"))
        return probe::driverSwitch(argv[2], getenv("A10VM_HWBINDER_PATH"));
    if (!strcmp(argv[1], "driver-polling")) return probe::driverPolling(argv[2]);
    if (!strcmp(argv[1], "driver-fork-close")) return probe::driverForkClose(argv[2]);
    if (!strcmp(argv[1], "registry")) return probe::registry();
    if (!strcmp(argv[1], "service")) return probe::service();
    if (!strcmp(argv[1], "client")) return probe::client(argv[2]);
    if (!strcmp(argv[1], "looper")) {
        android::ProcessState::self()->setThreadPoolMaxThreadCount(0);
        printf("binder_looper_ready=1\n");
        android::IPCThreadState::self()->joinThreadPool();
        printf("binder_looper_returned=1\n");
        return 0;
    }
    if (!strcmp(argv[1], "missing")) {
        auto state = android::ProcessState::initWithDriver(argv[2]);
        printf("binder_driver=%s\n", state->getDriverName().c_str());
        return state->getDriverName().isEmpty() ? 0 : 3;
    }
    return 2;
}
