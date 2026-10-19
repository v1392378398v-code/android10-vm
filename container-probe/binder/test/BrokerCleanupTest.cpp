#include "Broker.h"
#include <new>
#include <stdio.h>
#include <stdlib.h>

static size_t allocations;
void* operator new(size_t bytes) {
    ++allocations;
    void* result = malloc(bytes ? bytes : 1);
    if (!result) abort();
    return result;
}
void* operator new[](size_t bytes) { return ::operator new(bytes); }
void operator delete(void* pointer) noexcept { free(pointer); }
void operator delete[](void* pointer) noexcept { free(pointer); }

namespace a10binder {
class BrokerCleanupTest {
    static void require(bool passed, const char* name) {
        printf("CHECK\t%s\t%d\n", name, passed);
        if (!passed) exit(1);
    }

    static void prepare(Broker& broker) {
        broker.processes.emplace(1, Process{1, 2, 123, 10001});
        broker.connections.emplace(3, Connection{-1, {}});
        broker.connections.at(3).process = 1;
        broker.nextId = 10;
        for (uint64_t id = 10; id <= 19; ++id) {
            flat_binder_object object{};
            object.binder = id * 10;
            object.cookie = id * 100;
            require(broker.exportNode(3, object) == id, "export_cleanup_fixture_node");
        }
        broker.contextNode = 10;
        broker.nodes.at(11).strong = 1;
        broker.nodes.at(12).weak = 1;
        broker.nodes.at(13).pendingStrong = 1;
        broker.nodes.at(14).pendingWeak = 1;
        broker.nodes.at(15).asyncBusy = true;
        broker.nodes.at(16).asyncQueue.emplace_back();
        require(broker.importHandle(1, 17) == 1, "import_cleanup_fixture_handle");
        broker.contextNode = 18;
        Packet death;
        death.header.command = BC_REQUEST_DEATH_NOTIFICATION;
        death.append(binder_handle_cookie{0, 99});
        require(broker.command(3, std::move(death)) == 0, "request_cleanup_fixture_death");
        broker.contextNode = 10;
    }

    static std::set<uint64_t> reachable(const Broker& broker) {
        std::set<uint64_t> result;
        for (const auto& entry : broker.nodes) {
            const Node& node = entry.second;
            if (entry.first == broker.contextNode || node.strong || node.weak || node.pendingStrong ||
                node.pendingWeak || node.asyncBusy || !node.asyncQueue.empty()) result.insert(entry.first);
        }
        for (const auto& process : broker.processes) {
            for (const auto& handle : process.second.handles) result.insert(handle.second.node);
            for (const Death& death : process.second.deaths) result.insert(death.node);
        }
        return result;
    }

    static void checkReachable(const Broker& broker, const std::set<uint64_t>& expected) {
        std::set<uint64_t> actual;
        std::map<uint64_t, uint64_t> references;
        for (const auto& process : broker.processes) {
            for (const auto& handle : process.second.handles) ++references[handle.second.node];
            for (const Death& death : process.second.deaths) ++references[death.node];
        }
        for (const auto& entry : broker.nodes) {
            actual.insert(entry.first);
            require(entry.second.containerReferences == references[entry.first], "container_refs_match_live_tables");
        }
        require(actual == expected, "incremental_cleanup_matches_full_reachability_oracle");
    }

    static void collectChecked(Broker& broker) {
        auto expected = reachable(broker);
        broker.collectDeadNodes();
        checkReachable(broker, expected);
    }

    static void teardown(bool ownerFirst) {
        Broker broker;
        broker.processes.emplace(1, Process{1, 2, 123, 10001});
        broker.processes.emplace(2, Process{2, 4, 124, 10001});
        broker.connections.emplace(3, Connection{-1, {}});
        broker.connections.emplace(4, Connection{-1, {}});
        broker.connections.at(3).process = 1;
        broker.connections.at(4).process = 2;
        flat_binder_object object{};
        object.binder = 100;
        object.cookie = 1000;
        uint64_t node = broker.exportNode(3, object);
        uint32_t handle = broker.importHandle(2, node);
        require(broker.importHandle(2, node) == handle, "repeated_import_reuses_handle");
        Packet death;
        death.header.command = BC_REQUEST_DEATH_NOTIFICATION;
        death.append(binder_handle_cookie{handle, 99});
        require(broker.command(4, std::move(death)) == 0, "request_remote_death");
        collectChecked(broker);
        if (ownerFirst) {
            broker.closeProcess(1);
            collectChecked(broker);
            require(broker.nodes.count(node) && !broker.nodes.at(node).alive &&
                broker.processes.at(2).deaths.front().notified, "dead_owner_preserves_remote_handle_and_death");
            Packet clear;
            clear.header.command = BC_CLEAR_DEATH_NOTIFICATION;
            clear.append(binder_handle_cookie{handle, 99});
            require(broker.command(4, std::move(clear)) == 0, "clear_remote_death_after_owner_exit");
        } else broker.closeProcess(2);
        collectChecked(broker);
        require(!broker.nodes.count(node), "teardown_releases_last_container_references");
    }

    static void asyncBuffers() {
        Broker broker;
        broker.processes.emplace(1, Process{1, 2, 123, 10001});
        broker.connections.emplace(3, Connection{-1, {}});
        broker.connections.at(3).process = 1;
        flat_binder_object object{};
        object.binder = 100;
        object.cookie = 1000;
        uint64_t id = broker.exportNode(3, object);
        broker.nodes.at(id).asyncBusy = true;
        broker.nodes.at(id).asyncQueue.emplace_back();
        broker.buffers.emplace(100, Buffer{1, id, 16});
        broker.buffers.emplace(101, Buffer{1, id, 16});
        broker.processes.at(1).bufferBytes = 32;
        collectChecked(broker);
        require(broker.freeBuffer(1, 100) == 0, "release_first_async_buffer");
        collectChecked(broker);
        require(broker.nodes.count(id) && broker.nodes.at(id).asyncBusy &&
            broker.nodes.at(id).asyncQueue.empty(), "next_async_transaction_keeps_node_alive");
        require(broker.freeBuffer(1, 101) == 0, "release_last_async_buffer");
        collectChecked(broker);
        require(!broker.nodes.count(id), "last_async_buffer_reclaims_node");
    }

    static void multipleHandles() {
        Broker broker;
        broker.processes.emplace(1, Process{1, 2, 123, 10001});
        broker.processes.emplace(2, Process{2, 4, 124, 10001});
        broker.connections.emplace(3, Connection{-1, {}});
        broker.connections.at(3).process = 1;
        flat_binder_object object{};
        object.binder = 100;
        object.cookie = 1000;
        uint64_t id = broker.exportNode(3, object);
        uint32_t first = broker.importHandle(1, id), second = broker.importHandle(2, id);
        collectChecked(broker);
        broker.trimHandle(1, first);
        collectChecked(broker);
        require(broker.nodes.count(id), "another_context_handle_keeps_node_alive");
        broker.trimHandle(2, second);
        collectChecked(broker);
        require(!broker.nodes.count(id), "last_context_handle_reclaims_node");
    }

public:
    static void run() {
        Broker broker;
        prepare(broker);
        auto expected = reachable(broker);
        size_t before = allocations;
        broker.collectDeadNodes();
        size_t sweepAllocations = allocations - before;
        require(broker.nodes.size() == 9 && !broker.nodes.count(19), "cleanup_preserves_all_reachable_nodes");
        printf("broker_cleanup_allocations=%zu\n", sweepAllocations);
        require(sweepAllocations == 0, "cleanup_has_no_heap_allocations");
        checkReachable(broker, expected);
        broker.trimHandle(1, 1);
        collectChecked(broker);
        require(!broker.nodes.count(17) && broker.nodes.count(18), "cleanup_after_last_handle_removed");

        Packet clear;
        clear.header.command = BC_CLEAR_DEATH_NOTIFICATION;
        clear.append(binder_handle_cookie{0, 99});
        // Death notifications normally refer to a handle or the context manager.
        broker.contextNode = 18;
        require(broker.command(3, std::move(clear)) == 0, "clear_death_notification");
        broker.contextNode = 10;
        collectChecked(broker);
        require(!broker.nodes.count(18), "cleanup_after_last_death_removed");

        Packet done;
        done.header.command = BC_ACQUIRE_DONE;
        done.append(binder_ptr_cookie{130, 1300});
        require(broker.command(3, std::move(done)) == 0, "acquire_done");
        collectChecked(broker);
        require(!broker.nodes.count(13), "cleanup_after_pending_reference_ack");

        before = allocations;
        for (int index = 0; index < 1000; ++index) broker.collectDeadNodes();
        require(allocations == before, "unchanged_cleanup_has_no_heap_allocations");
        teardown(true);
        teardown(false);
        asyncBuffers();
        multipleHandles();
    }
};
}

int main() { a10binder::BrokerCleanupTest::run(); return 0; }
