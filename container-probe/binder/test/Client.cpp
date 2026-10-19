#include "Probe.h"
#include <fcntl.h>
#include <linux/memfd.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace probe {
class Callback final : public BBinder {
public:
    pid_t expectedTid, expectedPid;
    bool passed = false;
    status_t onTransact(uint32_t code, const Parcel& data, Parcel* reply, uint32_t) override {
        if (code != Nested) return UNKNOWN_TRANSACTION;
        sp<IBinder> remote = data.readStrongBinder();
        pid_t expectedServiceTid = data.readInt32();
        auto state = IPCThreadState::self();
        pid_t calling = state->getCallingPid();
        Parcel request, response;
        request.writeInt32(42);
        status_t status = remote->transact(Echo, request, &response);
        int value = response.readInt32(), pid = response.readInt32(), uid = response.readInt32();
        pid_t tid = response.readInt32();
        passed = gettid() == expectedTid && calling == expectedPid && status == OK &&
            value == 43 && pid == getpid() && uid == int(getuid()) && tid == expectedServiceTid &&
            state->getCallingPid() == calling;
        reply->writeInt32(passed);
        return OK;
    }
};
class DeathRecipient final : public IBinder::DeathRecipient {
public:
    std::mutex mutex;
    std::condition_variable condition;
    std::atomic<int> count{0};
    void binderDied(const wp<IBinder>&) override {
        std::lock_guard<std::mutex> lock(mutex);
        ++count; condition.notify_all();
    }
};
int client(const char* path) {
    bool passed = true;
    auto test = [&](const char* name, bool result) { passed &= check(name, result); };
    ProcessState::self()->setThreadPoolMaxThreadCount(0);
    sp<IServiceManager> manager = defaultServiceManager();
    sp<IBinder> remote = findService();
    if (!check("client_service_found", remote != nullptr)) return 3;
    test("registry_missing", manager->checkService(String16("a10vm.absent")) == nullptr);
    Vector<String16> services = manager->listServices();
    test("registry_list", services.size() == 1 && services[0] == String16(kService));
    status_t status;
    {
        std::vector<uint8_t> bytes(512 * 1024);
        for (size_t i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<uint8_t>(i * 31);
        Parcel request, response;
        request.write(bytes.data(), bytes.size());
        status = remote->transact(LargeEcho, request, &response);
        test("large_parcel_roundtrip", status == OK && response.dataSize() == bytes.size() &&
             !memcmp(response.data(), bytes.data(), bytes.size()));
    }
    {
        Parcel echo, echoed;
        echo.writeInt32(7);
        status = remote->transact(Echo, echo, &echoed);
        test("rpc_value", status == OK && echoed.readInt32() == 8);
        test("rpc_sender_identity", echoed.readInt32() == getpid() && echoed.readInt32() == int(getuid()));
    }
    sp<Callback> callback = new Callback;
    callback->expectedTid = gettid();
    {
        Parcel nested, nestedReply;
        nested.writeStrongBinder(callback);
        // The server PID is supplied by the harness so no host Binder lookup is involved.
        callback->expectedPid = atoi(getenv("A10VM_SERVICE_PID"));
        status = remote->transact(Nested, nested, &nestedReply);
        test("nested_same_thread", status == OK && nestedReply.readInt32() == OK && nestedReply.readInt32() == 1 && callback->passed);
        test("nested_identity_restored", nestedReply.readInt32() == 1);
        test("clear_restore_identity", nestedReply.readInt32() == 1);
    }
    {
        Parcel object, returned;
        object.writeStrongBinder(callback);
        status = remote->transact(ReturnObject, object, &returned);
        test("object_roundtrip", status == OK && returned.readStrongBinder() == callback);
    }
    {
        int fd = syscall(__NR_memfd_create, "a10vm-binder-test", MFD_CLOEXEC);
        const char content[] = "binder-fd-data";
        bool valid = fd >= 0 && write(fd, content, sizeof(content)) == sizeof(content);
        int received = -1;
        {
            Parcel request, response;
            request.writeFileDescriptor(fd, false);
            status = remote->transact(Descriptor, request, &response);
            int count = response.readInt32();
            String8 text = response.readString8();
            received = response.readFileDescriptor();
            char bytes[32]{};
            valid &= status == OK && count == sizeof(content) && text == String8(content) &&
                received >= 0 && pread(received, bytes, sizeof(bytes), 0) == sizeof(content) &&
                !strcmp(bytes, content) && (fcntl(received, F_GETFD) & FD_CLOEXEC);
            test("fd_content_and_cloexec", valid);
        }
        test("fd_parcel_closed", received >= 0 && fcntl(received, F_GETFD) == -1 && errno == EBADF);
        test("fd_sender_retained", fcntl(fd, F_GETFD) >= 0);
        close(fd);
    }
    for (int n = 0; n < kMessages; ++n) {
        Parcel request;
        request.writeInt32(n);
        passed &= remote->transact(Oneway, request, nullptr, IBinder::FLAG_ONEWAY) == OK;
    }
    bool ordered = false;
    for (int n = 0; n < 100; ++n) {
        Parcel request, response;
        if (remote->transact(Snapshot, request, &response) != OK) break;
        int count = response.readInt32();
        ordered = count == kMessages && response.readInt32() == 1;
        if (ordered) break;
        usleep(10000);
    }
    test("oneway_order", ordered);
    std::atomic<int> finished{0};
    std::vector<std::thread> workers;
    for (int n = 0; n < 8; ++n) workers.emplace_back([&] {
        Parcel request, response;
        if (remote->transact(Concurrent, request, &response) == OK && response.readInt32() > 0) ++finished;
    });
    for (auto& worker : workers) worker.join();
    test("concurrent_rpc", finished == 8);
    {
        Parcel request, response;
        remote->transact(Snapshot, request, &response);
        response.readInt32(); response.readInt32();
        int peak = response.readInt32();
        test("pool_parallelism", peak >= 2 && peak <= 3);
    }
    IPCThreadState::self()->flushCommands();
    a10binder::Stats beforeObjects{};
    a10binder::inspect(path, &beforeObjects);
    bool created = true;
    for (int n = 0; n < 32; ++n) {
        Parcel request, response;
        status = remote->transact(MakeObject, request, &response);
        sp<IBinder> temporary = response.readStrongBinder();
        created &= status == OK && temporary != nullptr;
    }
    test("temporary_object_repeat", created);
    IPCThreadState::self()->flushCommands();
    bool destroyed = false;
    for (int n = 0; n < 100; ++n) {
        Parcel request, response;
        if (remote->transact(Destructors, request, &response) == OK && response.readInt32() == 32) { destroyed = true; break; }
        usleep(10000);
    }
    test("remote_object_destructors", destroyed);
    IPCThreadState::self()->flushCommands();
    a10binder_buffer_stats local{};
    a10binder_get_buffer_stats(&local);
    test("client_buffers_reclaimed_alive", local.active == 0 && local.bytes == 0 && local.allocated == local.freed);
    a10binder::Stats afterObjects{};
    bool nodesReclaimed = false;
    for (int n = 0; n < 100; ++n) {
        if (a10binder::inspect(path, &afterObjects) != 0) break;
        if (afterObjects.nodes <= beforeObjects.nodes && afterObjects.buffers == 0 &&
            afterObjects.calls == 0 && afterObjects.pendingReferences == 0) { nodesReclaimed = true; break; }
        usleep(10000);
    }
    printf("binder_live_resources=%llu,%llu,%llu,%llu,%llu\n",
        (unsigned long long)beforeObjects.nodes, (unsigned long long)afterObjects.nodes,
        (unsigned long long)afterObjects.buffers, (unsigned long long)afterObjects.calls,
        (unsigned long long)afterObjects.pendingReferences);
    printf("binder_live_buffer_owner=%llu,%llu\n",
        (unsigned long long)afterObjects.largestBufferOwnerPid,
        (unsigned long long)afterObjects.largestBufferOwnerBytes);
    printf("binder_live_buffer_command=%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu\n",
        (unsigned long long)afterObjects.largestBufferId,
        (unsigned long long)afterObjects.largestBufferOwnerProcess,
        (unsigned long long)afterObjects.largestBufferCommand,
        (unsigned long long)afterObjects.largestBufferTransactionCode,
        (unsigned long long)afterObjects.largestBufferDataBytes,
        (unsigned long long)afterObjects.largestBufferOffsetsBytes,
        (unsigned long long)afterObjects.largestBufferFlags,
        (unsigned long long)afterObjects.largestBufferCallId,
        (unsigned long long)afterObjects.largestBufferSenderPid,
        (unsigned long long)afterObjects.largestBufferIsReply);
    test("live_nodes_reclaimed", nodesReclaimed);
    sp<DeathRecipient> recipient = new DeathRecipient;
    test("death_subscribe", remote->linkToDeath(recipient) == OK);
    std::thread looper([] { IPCThreadState::self()->joinThreadPool(); });
    {
        Parcel request, response;
        status = remote->transact(Die, request, &response);
        test("death_during_call", status == DEAD_OBJECT);
    }
    {
        std::unique_lock<std::mutex> lock(recipient->mutex);
        test("death_notification", waitFor(recipient->condition, lock, recipient->count, 1));
    }
    Parcel dead, deadReply;
    test("dead_object_reply", remote->transact(Echo, dead, &deadReply) == DEAD_OBJECT);
    a10binder::Stats stats{};
    test("broker_inspect", a10binder::inspect(path, &stats) == 0);
    printf("binder_client_complete=%d\n", passed);
    IPCThreadState::self()->stopProcess();
    looper.join();
    printf("binder_client_returned=1\n");
    return passed ? 0 : 3;
}
}
