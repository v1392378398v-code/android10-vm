#pragma once
#include <binder/Binder.h>
#include <binder/IPCThreadState.h>
#include <binder/IServiceManager.h>
#include <binder/Parcel.h>
#include <binder/ProcessState.h>
#include <utils/String8.h>
#include "Driver.h"
#include "Wire.h"
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

namespace probe {
using namespace android;
enum Code : uint32_t { Echo = IBinder::FIRST_CALL_TRANSACTION, Nested, ReturnObject,
    Descriptor, Oneway, Snapshot, MakeObject, Destructors, Concurrent, Die, Hold, LargeEcho };
constexpr const char* kService = "a10vm.probe";
constexpr int kMessages = 24;
bool check(const char* name, bool passed);
int registry();
int service();
int client(const char* path);
int resources(const char* path);
int driverSwitch(const char* binder, const char* hardware);
int driverPolling(const char* binder);
int driverForkClose(const char* binder);
int descriptorCount();
bool waitFor(std::condition_variable& condition, std::unique_lock<std::mutex>& lock,
             const std::atomic<int>& value, int expected);
sp<IBinder> findService();
}
