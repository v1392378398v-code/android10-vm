#include "Probe.h"
#include <stdio.h>

namespace hwbinder_probe {
class Registry final : public BHwBinder {
    sp<IBinder> service;

    status_t onTransact(uint32_t code, const Parcel& data, Parcel* reply, uint32_t,
            TransactCallback) override {
        switch (code) {
            case Register: {
                if (data.readString16() != String16(kService)) return BAD_VALUE;
                service = data.readStrongBinder();
                return reply->writeInt32(service == nullptr ? BAD_VALUE : OK);
            }
            case Lookup:
                if (data.readString16() != String16(kService)) return reply->writeStrongBinder(nullptr);
                return reply->writeStrongBinder(service);
            default:
                return UNKNOWN_TRANSACTION;
        }
    }
};

bool check(const char* name, bool passed) {
    printf("CHECK\t%s\t%d\n", name, passed);
    fflush(stdout);
    return passed;
}

int registry() {
    sp<ProcessState> process = ProcessState::self();
    sp<Registry> object = new Registry;
    process->setContextObject(object);
    IPCThreadState::self()->setTheContextObject(object);
    bool ready = process->becomeContextManager(nullptr, nullptr);
    check("hwbinder_registry_context", ready);
    if (!ready) return 3;
    printf("hwbinder_registry_ready=1\n");
    IPCThreadState::self()->joinThreadPool();
    printf("hwbinder_registry_returned=1\n");
    return 0;
}
}
