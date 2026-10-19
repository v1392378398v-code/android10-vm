#include "Probe.h"
#include <cutils/native_handle.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>

namespace hwbinder_probe {
namespace {
struct Text { const char* bytes; size_t size; };
struct Payload { const Text* items; size_t count; };

int descriptorCount() {
    DIR* directory = opendir("/proc/self/fd");
    if (!directory) return -1;
    int count = 0;
    while (dirent* entry = readdir(directory)) if (entry->d_name[0] != '.') ++count;
    closedir(directory);
    return count;
}

status_t writePayload(Parcel* parcel, const Payload& payload) {
    size_t root, items;
    status_t status = parcel->writeBuffer(&payload, sizeof(payload), &root);
    if (status == OK) status = parcel->writeEmbeddedBuffer(payload.items,
            payload.count * sizeof(Text), &items, root, offsetof(Payload, items));
    for (size_t n = 0; status == OK && n < payload.count; ++n) {
        status = parcel->writeEmbeddedBuffer(payload.items[n].bytes, payload.items[n].size,
                nullptr, items, n * sizeof(Text) + offsetof(Text, bytes));
    }
    return status;
}

status_t readPayload(const Parcel& parcel, const Payload** payload) {
    size_t root, items;
    const void *rootData, *itemData, *textData;
    status_t status = parcel.readBuffer(sizeof(Payload), &root, &rootData);
    if (status != OK) return status;
    const auto* value = static_cast<const Payload*>(rootData);
    if (value->count != 2) return BAD_VALUE;
    status = parcel.readEmbeddedBuffer(value->count * sizeof(Text), &items, root,
            offsetof(Payload, items), &itemData);
    if (status != OK || itemData != value->items) return BAD_VALUE;
    for (size_t n = 0; n < value->count; ++n) {
        if (value->items[n].size == 0 || value->items[n].size > 64) return BAD_VALUE;
        status = parcel.readEmbeddedBuffer(value->items[n].size, nullptr, items,
                n * sizeof(Text) + offsetof(Text, bytes), &textData);
        if (status != OK || textData != value->items[n].bytes) return BAD_VALUE;
    }
    *payload = value;
    return OK;
}

int serviceDescriptors(const sp<IBinder>& remote) {
    Parcel request, response;
    if (remote->transact(ServiceDescriptors, request, &response) != OK) return -1;
    return response.readInt32();
}
}

status_t bufferTransaction(uint32_t code, const Parcel& data, Parcel* reply,
        const BHwBinder::TransactCallback& callback) {
    status_t status;
    if (code == BufferRoundTrip) {
        const Payload* payload;
        status = readPayload(data, &payload);
        if (status == OK) status = writePayload(reply, *payload);
    } else if (code == HandleRoundTrip) {
        const native_handle_t* handle;
        status = data.readNativeHandleNoDup(&handle);
        if (status == OK) status = reply->writeNativeHandleNoDup(handle);
    } else if (code == ServiceDescriptors) {
        return reply->writeInt32(descriptorCount());
    } else {
        return hidlValueTransaction(code, data, reply, callback);
    }
    // Pointer-backed reply storage belongs to the incoming Parcel until this returns.
    if (status == OK) callback(*reply);
    return status;
}

bool bufferTests(const sp<IBinder>& remote) {
    bool passed = true;
    auto test = [&](const char* name, bool value) { passed &= check(name, value); };
    {
        Text items[] = {{"Android 10", 11}, {"nested buffer", 14}};
        Payload payload{items, 2};
        Parcel request, response;
        const Payload* received = nullptr;
        status_t status = writePayload(&request, payload);
        if (status == OK) status = remote->transact(BufferRoundTrip, request, &response);
        if (status == OK) status = readPayload(response, &received);
        bool same = status == OK;
        for (size_t n = 0; same && n < payload.count; ++n) {
            same = received->items[n].size == items[n].size &&
                    memcmp(received->items[n].bytes, items[n].bytes, items[n].size) == 0;
        }
        test("hwbinder_nested_buffer_roundtrip", same);
        if (!same) return false;
    }
    IPCThreadState::self()->flushCommands();
    int localBefore = descriptorCount(), serviceBefore = serviceDescriptors(remote);
    bool roundtrip = true, cloexec = true, closed = true;
    for (int round = 0; round < 16; ++round) {
        int pipeFds[2];
        if (pipe2(pipeFds, O_CLOEXEC) != 0) return false;
        native_handle_t* sent = native_handle_create(2, 1);
        if (!sent) { close(pipeFds[0]); close(pipeFds[1]); return false; }
        sent->data[0] = pipeFds[0]; sent->data[1] = pipeFds[1]; sent->data[2] = 1234 + round;
        int receivedFds[2] = {-1, -1};
        {
            Parcel request, response;
            const native_handle_t* received = nullptr;
            status_t status = request.writeNativeHandleNoDup(sent);
            if (status == OK) status = remote->transact(HandleRoundTrip, request, &response);
            if (status == OK) status = response.readNativeHandleNoDup(&received);
            bool valid = status == OK && received->numFds == 2 && received->numInts == 1
                    && received->data[2] == sent->data[2];
            if (valid) {
                receivedFds[0] = received->data[0]; receivedFds[1] = received->data[1];
                char value = static_cast<char>('a' + round), result = 0;
                valid = write(receivedFds[1], &value, 1) == 1 && read(pipeFds[0], &result, 1) == 1
                        && result == value;
                cloexec &= (fcntl(receivedFds[0], F_GETFD) & FD_CLOEXEC) != 0
                        && (fcntl(receivedFds[1], F_GETFD) & FD_CLOEXEC) != 0;
            }
            roundtrip &= valid;
        }
        IPCThreadState::self()->flushCommands();
        for (int fd : receivedFds) closed &= fd >= 0 && fcntl(fd, F_GETFD) == -1 && errno == EBADF;
        native_handle_close(sent);
        native_handle_delete(sent);
    }
    test("hwbinder_native_handle_roundtrip", roundtrip);
    test("hwbinder_fd_array_cloexec", cloexec);
    test("hwbinder_fd_array_closed_on_free", closed);
    test("hwbinder_fd_array_no_leaks", localBefore >= 0 && serviceBefore >= 0 &&
            descriptorCount() == localBefore && serviceDescriptors(remote) == serviceBefore);
    return passed;
}
}
