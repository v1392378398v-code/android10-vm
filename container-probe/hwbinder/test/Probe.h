#pragma once
#include <hwbinder/Binder.h>
#include <hwbinder/IPCThreadState.h>
#include <hwbinder/Parcel.h>
#include <hwbinder/ProcessState.h>
#include <utils/Errors.h>
#include <utils/String16.h>
#include <stdint.h>
#include <stdlib.h>

namespace hwbinder_probe {
using namespace android;
using namespace android::hardware;

enum Code : uint32_t {
    Register = 1, Lookup, Echo, InvokeCallback, CallbackCall,
    BufferRoundTrip, HandleRoundTrip, ServiceDescriptors,
    HidlVectorRoundTrip, HidlMemoryRoundTrip,
};
constexpr const char* kService = "a10vm.hwbinder.probe";

bool check(const char* name, bool passed);
int registry();
int service();
int client();
int looper();
bool bufferTests(const sp<IBinder>& remote);
status_t bufferTransaction(uint32_t code, const Parcel& data, Parcel* reply,
        const BHwBinder::TransactCallback& callback);
bool hidlValueTests(const sp<IBinder>& remote);
status_t hidlValueTransaction(uint32_t code, const Parcel& data, Parcel* reply,
        const BHwBinder::TransactCallback& callback);
}
