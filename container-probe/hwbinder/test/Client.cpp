#include "Probe.h"
#include <stdio.h>
#include <unistd.h>

namespace hwbinder_probe {
static pid_t servicePid() {
    const char* value = getenv("A10VM_HWBINDER_SERVICE_PID");
    return value == nullptr ? -1 : static_cast<pid_t>(atoi(value));
}

class Callback final : public BHwBinder {
    status_t onTransact(uint32_t code, const Parcel& data, Parcel* reply, uint32_t,
            TransactCallback) override {
        if (code != CallbackCall) return UNKNOWN_TRANSACTION;
        sp<IBinder> remote = data.readStrongBinder();
        int32_t value = data.readInt32();
        IPCThreadState* state = IPCThreadState::self();
        pid_t caller = state->getCallingPid();
        Parcel request, response;
        request.writeInt32(value);
        status_t status = remote->transact(Echo, request, &response);
        int32_t echoed = response.readInt32();
        int32_t echoCaller = response.readInt32();
        reply->writeInt32(value + 1);
        reply->writeInt32(echoed);
        reply->writeInt32(caller);
        reply->writeInt32(echoCaller);
        reply->writeInt32(status == OK && state->getCallingPid() == caller);
        return OK;
    }
};

int client() {
    bool passed = true;
    auto test = [&](const char* name, bool value) { passed &= check(name, value); };
    sp<IBinder> manager = ProcessState::self()->getContextObject(nullptr);
    test("hwbinder_context_manager_found", manager != nullptr);
    if (manager == nullptr) return 3;

    Parcel lookup, lookupReply;
    lookup.writeString16(String16(kService));
    status_t status = manager->transact(Lookup, lookup, &lookupReply);
    sp<IBinder> remote = status == OK ? lookupReply.readStrongBinder() : nullptr;
    test("hwbinder_service_lookup", remote != nullptr);
    if (remote == nullptr) return 3;

    {
        Parcel request, response;
        request.writeInt32(7);
        status = remote->transact(Echo, request, &response);
        test("hwbinder_sync_rpc", status == OK && response.readInt32() == 8 &&
                response.readInt32() == getpid());
    }
    {
        sp<Callback> callback = new Callback;
        Parcel request, response;
        request.writeStrongBinder(callback);
        request.writeInt32(18);
        status = remote->transact(InvokeCallback, request, &response);
        int32_t callbackStatus = response.readInt32();
        int32_t callbackValue = response.readInt32();
        int32_t nestedValue = response.readInt32();
        int32_t callbackCaller = response.readInt32();
        int32_t nestedCaller = response.readInt32();
        int32_t callbackIdentityRestored = response.readInt32();
        int32_t serviceIdentityRestored = response.readInt32();
        pid_t expectedServicePid = servicePid();
        test("hwbinder_callback_delivery", status == OK && callbackStatus == OK && callbackValue == 19);
        test("hwbinder_callback_nested_rpc", nestedValue == 19 && nestedCaller == getpid());
        test("hwbinder_callback_calling_identity", callbackCaller == expectedServicePid);
        test("hwbinder_callback_identity_restored",
                callbackIdentityRestored == 1 && serviceIdentityRestored == 1);
    }
    passed &= bufferTests(remote);
    passed &= hidlValueTests(remote);
    printf("hwbinder_client_complete=%d\n", passed);
    return passed ? 0 : 3;
}

int looper() {
    ProcessState::self();
    printf("hwbinder_looper_ready=1\n");
    IPCThreadState::self()->joinThreadPool();
    printf("hwbinder_looper_returned=1\n");
    return 0;
}
}
