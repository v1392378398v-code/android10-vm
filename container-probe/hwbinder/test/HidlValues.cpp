#include "Probe.h"
#include <hidl/HidlValueSupport.h>
#include <cutils/ashmem.h>
#include <unistd.h>

namespace hwbinder_probe {
namespace {
using Strings = hidl_vec<hidl_string>;
status_t writeStrings(Parcel* parcel, const Strings& strings) {
    size_t root, items;
    status_t status = parcel->writeBuffer(&strings, sizeof(strings), &root);
    if (status == OK) status = writeEmbeddedToParcel(strings, parcel, root, 0, &items);
    for (size_t n = 0; status == OK && n < strings.size(); ++n) {
        status = writeEmbeddedToParcel(strings[n], parcel, items, n * sizeof(hidl_string));
    }
    return status;
}
status_t readStrings(const Parcel& parcel, const Strings** strings) {
    size_t root, items;
    status_t status = parcel.readBuffer(sizeof(Strings), &root, reinterpret_cast<const void**>(strings));
    if (status != OK || (*strings)->size() > 16) return BAD_VALUE;
    status = readEmbeddedFromParcel(**strings, parcel, root, 0, &items);
    for (size_t n = 0; status == OK && n < (*strings)->size(); ++n) {
        if ((**strings)[n].size() > 64) return BAD_VALUE;
        status = readEmbeddedFromParcel((**strings)[n], parcel, items, n * sizeof(hidl_string));
    }
    return status;
}
bool stringsRoundTrip(const sp<IBinder>& remote, const Strings& sent) {
    Parcel request, response;
    const Strings* received = nullptr;
    status_t status = writeStrings(&request, sent);
    if (status == OK) status = remote->transact(HidlVectorRoundTrip, request, &response);
    if (status == OK) status = readStrings(response, &received);
    return status == OK && *received == sent;
}
status_t writeMemory(Parcel* parcel, const hidl_memory& memory) {
    size_t root;
    status_t status = parcel->writeBuffer(&memory, sizeof(memory), &root);
    return status == OK ? writeEmbeddedToParcel(memory, parcel, root, 0) : status;
}
status_t readMemory(const Parcel& parcel, const hidl_memory** memory) {
    size_t root;
    status_t status = parcel.readBuffer(sizeof(hidl_memory), &root, reinterpret_cast<const void**>(memory));
    return status == OK ? readEmbeddedFromParcel(**memory, parcel, root, 0) : status;
}
}

status_t hidlValueTransaction(uint32_t code, const Parcel& data, Parcel* reply,
        const BHwBinder::TransactCallback& callback) {
    status_t status;
    if (code == HidlVectorRoundTrip) {
        const Strings* strings;
        status = readStrings(data, &strings);
        if (status == OK) status = writeStrings(reply, *strings);
    } else if (code == HidlMemoryRoundTrip) {
        const hidl_memory* memory;
        status = readMemory(data, &memory);
        if (status != OK || memory->name() != "a10vm-shared" || memory->size() != 4096 ||
            !memory->handle() || memory->handle()->numFds != 1) return BAD_VALUE;
        int value = 0;
        int fd = memory->handle()->data[0];
        if (pread(fd, &value, sizeof(value), 0) != sizeof(value) || value != 100) return BAD_VALUE;
        ++value;
        if (pwrite(fd, &value, sizeof(value), 0) != sizeof(value)) return BAD_VALUE;
        status = writeMemory(reply, *memory);
    } else {
        return UNKNOWN_TRANSACTION;
    }
    if (status == OK) callback(*reply);
    return status;
}

bool hidlValueTests(const sp<IBinder>& remote) {
    bool passed = true;
    auto test = [&](const char* name, bool value) { passed &= check(name, value); };
    Strings strings{"Android 10", "", "HIDL buffers"};
    test("hidl_string_vector_roundtrip", stringsRoundTrip(remote, strings));
    test("hidl_empty_vector_roundtrip", stringsRoundTrip(remote, Strings{}));
    {
        Strings broken{"bad"};
        const_cast<char*>(broken[0].c_str())[broken[0].size()] = '!';
        Parcel request, response;
        status_t status = writeStrings(&request, broken);
        test("hidl_string_terminator_validation", status == OK &&
                remote->transact(HidlVectorRoundTrip, request, &response) == BAD_VALUE);
    }
    {
        int fd = ashmem_create_region("a10vm-hidl", 4096);
        native_handle_t* handle = native_handle_create(1, 0);
        if (fd < 0 || !handle) {
            if (fd >= 0) close(fd);
            if (handle) native_handle_delete(handle);
            test("hidl_shared_memory_roundtrip", false);
            return false;
        }
        handle->data[0] = fd;
        int before = 100, after = 0;
        bool ok = pwrite(fd, &before, sizeof(before), 0) == sizeof(before);
        {
            hidl_memory memory("a10vm-shared", handle, 4096);
            Parcel request, response;
            const hidl_memory* received = nullptr;
            status_t status = writeMemory(&request, memory);
            if (status == OK) status = remote->transact(HidlMemoryRoundTrip, request, &response);
            if (status == OK) status = readMemory(response, &received);
            ok &= status == OK && received->name() == memory.name() && received->size() == memory.size() &&
                    received->handle() && received->handle()->numFds == 1 &&
                    pread(received->handle()->data[0], &after, sizeof(after), 0) == sizeof(after) && after == 101 &&
                    pread(fd, &after, sizeof(after), 0) == sizeof(after) && after == 101;
        }
        IPCThreadState::self()->flushCommands();
        native_handle_close(handle); native_handle_delete(handle);
        test("hidl_shared_memory_roundtrip", ok);
    }
    return passed;
}
}
