#include "Probe.h"
#include <stdio.h>
#include <unistd.h>

namespace hwbinder_probe {
class Service final : public BHwBinder {
    status_t onTransact(uint32_t code, const Parcel& data, Parcel* reply, uint32_t,
            TransactCallback callback) override {
        IPCThreadState* state = IPCThreadState::self();
        switch (code) {
            case Echo:
                reply->writeInt32(data.readInt32() + 1);
                return reply->writeInt32(state->getCallingPid());
            case InvokeCallback: {
                sp<IBinder> callback = data.readStrongBinder();
                int32_t value = data.readInt32();
                pid_t caller = state->getCallingPid();
                Parcel request, response;
                request.writeStrongBinder(this);
                request.writeInt32(value);
                status_t status = callback->transact(CallbackCall, request, &response);
                reply->writeInt32(status);
                for (int n = 0; n < 5; ++n) reply->writeInt32(response.readInt32());
                reply->writeInt32(state->getCallingPid() == caller);
                return OK;
            }
            default:
                return bufferTransaction(code, data, reply, callback);
        }
    }
};

int service() {
    sp<IBinder> manager = ProcessState::self()->getContextObject(nullptr);
    if (manager == nullptr) return 3;
    sp<IBinder> object = new Service;
    Parcel request, response;
    request.writeString16(String16(kService));
    request.writeStrongBinder(object);
    status_t status = manager->transact(Register, request, &response);
    bool registered = status == OK && response.readInt32() == OK;
    check("hwbinder_service_registered", registered);
    if (!registered) return 3;
    printf("hwbinder_service_ready=1\n");
    IPCThreadState::self()->joinThreadPool();
    printf("hwbinder_service_returned=1\n");
    return 0;
}
}
