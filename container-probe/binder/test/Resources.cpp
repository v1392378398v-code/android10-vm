#include "Probe.h"
#include <dirent.h>
#include <chrono>
#include <stdio.h>

namespace probe {
int descriptorCount() {
    DIR* directory = opendir("/proc/self/fd");
    if (!directory) return -1;
    int count = 0;
    while (dirent* entry = readdir(directory)) if (entry->d_name[0] != '.') ++count;
    closedir(directory);
    return count;
}
bool waitFor(std::condition_variable& condition, std::unique_lock<std::mutex>& lock,
             const std::atomic<int>& value, int expected) {
    return condition.wait_for(lock, std::chrono::seconds(3), [&] { return value == expected; });
}
int resources(const char* path) {
    a10binder::Stats stats{};
    if (a10binder::inspect(path, &stats) != 0) return 3;
    printf("STATS\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t"
           "%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t"
           "%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t"
           "%llu\t%llu\t%llu\t%llu\n",
        (unsigned long long)stats.processes, (unsigned long long)stats.threads,
        (unsigned long long)stats.nodes, (unsigned long long)stats.handles,
        (unsigned long long)stats.buffers, (unsigned long long)stats.calls,
        (unsigned long long)stats.deaths, (unsigned long long)stats.queuedFds,
        (unsigned long long)stats.transactions, (unsigned long long)stats.replies,
        (unsigned long long)stats.oneways, (unsigned long long)stats.freed,
        (unsigned long long)stats.disconnected, (unsigned long long)stats.pendingReferences,
        (unsigned long long)stats.registeredLoopers, (unsigned long long)stats.spawns,
        (unsigned long long)stats.largestBufferOwnerPid, (unsigned long long)stats.largestBufferOwnerBytes,
        (unsigned long long)stats.largestBufferCommand, (unsigned long long)stats.largestBufferDataBytes,
        (unsigned long long)stats.largestBufferId, (unsigned long long)stats.largestBufferOwnerProcess,
        (unsigned long long)stats.largestBufferSenderPid, (unsigned long long)stats.largestBufferTransactionCode,
        (unsigned long long)stats.largestBufferFlags, (unsigned long long)stats.largestBufferOffsetsBytes,
        (unsigned long long)stats.largestBufferCallId, (unsigned long long)stats.largestBufferIsReply);
    return 0;
}
}
