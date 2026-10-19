#include "Broker.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

namespace a10binder {
class BrokerReclaimBenchmark {
    static uint64_t cpuNanos() {
        timespec now{};
        if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &now) != 0) abort();
        return uint64_t(now.tv_sec) * 1000000000 + now.tv_nsec;
    }

    static uint64_t measure(size_t rootedNodes, int rounds) {
        Broker broker;
        broker.processes.emplace(1, Process{1, 2, 123, 10001});
        broker.nextId = 10;
        for (size_t index = 0; index < rootedNodes; ++index) {
            uint64_t id = broker.nextId++;
            broker.nodes.emplace(id, Node{id, 1, 0, id, id, 0});
            broker.scheduleNodeReclaim(broker.nodes.at(id));
            uint32_t handle = broker.importHandle(1, id);
            broker.processes.at(1).handles.at(handle).temporary = 1;
        }
        broker.collectDeadNodes();
        uint64_t elapsed = 0;
        for (int index = 0; index < rounds; ++index) {
            uint64_t id = broker.nextId++;
            broker.nodes.emplace(id, Node{id, 1, 0, id, id, 0});
            broker.scheduleNodeReclaim(broker.nodes.at(id));
            uint32_t handle = broker.importHandle(1, id);
            broker.trimHandle(1, handle);
            uint64_t started = cpuNanos();
            broker.collectDeadNodes();
            elapsed += cpuNanos() - started;
            if (broker.nodes.count(id) || broker.nodes.size() != rootedNodes) abort();
        }
        return elapsed / rounds;
    }

public:
    static int run() {
        constexpr int rounds = 300;
        uint64_t empty = measure(0, rounds), populated = measure(12000, rounds);
        bool passed = populated < 50000;
        printf("{\"rootedNodes\":12000,\"rounds\":%d,\"emptyCpuNanosPerCollection\":%llu,"
               "\"populatedCpuNanosPerCollection\":%llu,\"maxCpuNanosPerCollection\":50000,"
               "\"passed\":%s,\"limitation\":\"Isolated real node collection; excludes export, IPC and rendering\"}\n",
               rounds, (unsigned long long)empty, (unsigned long long)populated, passed ? "true" : "false");
        return passed ? 0 : 1;
    }
};
}

int main() { return a10binder::BrokerReclaimBenchmark::run(); }
