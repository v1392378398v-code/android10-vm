#include "Probe.h"
#include <sys/stat.h>
#include <stdio.h>
#include <unistd.h>
#include <vector>

namespace probe {
static std::atomic<int> destroyed{0};
class Temporary final : public BBinder {
public:
    ~Temporary() override { ++destroyed; }
};
class Service final : public BBinder {
    std::mutex mutex;
    std::vector<int> messages;
    bool ordered = true;
    std::atomic<int> active{0}, peak{0};
    status_t onTransact(uint32_t code, const Parcel& data, Parcel* reply, uint32_t) override {
        IPCThreadState* state = IPCThreadState::self();
        switch (code) {
            case LargeEcho:
                return reply->write(data.data(), data.dataSize());
            case Echo:
                reply->writeInt32(data.readInt32() + 1);
                reply->writeInt32(state->getCallingPid());
                reply->writeInt32(state->getCallingUid());
                reply->writeInt32(gettid());
                return OK;
            case Nested: {
                sp<IBinder> callback = data.readStrongBinder();
                pid_t caller = state->getCallingPid();
                uid_t uid = state->getCallingUid();
                pid_t tid = gettid();
                Parcel request, result;
                request.writeStrongBinder(this);
                request.writeInt32(tid);
                status_t status = callback->transact(Nested, request, &result);
                reply->writeInt32(status);
                reply->writeInt32(result.readInt32());
                reply->writeInt32(state->getCallingPid() == caller && state->getCallingUid() == uid);
                int64_t token = state->clearCallingIdentity();
                bool cleared = state->getCallingPid() == getpid() && state->getCallingUid() == getuid();
                state->restoreCallingIdentity(token);
                reply->writeInt32(cleared && state->getCallingPid() == caller && state->getCallingUid() == uid);
                return OK;
            }
            case ReturnObject:
                return reply->writeStrongBinder(data.readStrongBinder());
            case Descriptor: {
                int fd = data.readFileDescriptor();
                char bytes[16]{};
                ssize_t count = pread(fd, bytes, sizeof(bytes), 0);
                reply->writeInt32(count);
                reply->writeString8(String8(bytes));
                return reply->writeDupFileDescriptor(fd);
            }
            case Oneway: {
                int n = data.readInt32();
                usleep(2000);
                std::lock_guard<std::mutex> lock(mutex);
                ordered &= n == int(messages.size());
                messages.push_back(n);
                return OK;
            }
            case Snapshot: {
                std::lock_guard<std::mutex> lock(mutex);
                reply->writeInt32(messages.size());
                reply->writeInt32(ordered);
                reply->writeInt32(peak);
                return OK;
            }
            case MakeObject:
                return reply->writeStrongBinder(new Temporary);
            case Destructors:
                reply->writeInt32(destroyed); return OK;
            case Concurrent: {
                int current = ++active;
                int observed = peak;
                while (current > observed && !peak.compare_exchange_weak(observed, current)) { }
                usleep(30000);
                --active; reply->writeInt32(gettid()); return OK;
            }
            case Die: _exit(0);
            case Hold: printf("binder_hold_entered=1\n"); for (;;) pause();
            default: return BBinder::onTransact(code, data, reply);
        }
    }
};
int service() {
    ProcessState::self()->setThreadPoolMaxThreadCount(2);
    sp<IBinder> object = new Service;
    status_t status = defaultServiceManager()->addService(String16(kService), object);
    if (!check("service_registered", status == OK)) return 3;
    IPCThreadState::self()->flushCommands();
    ProcessState::self()->startThreadPool();
    printf("binder_service_ready=1\n");
    for (;;) pause();
}
}
