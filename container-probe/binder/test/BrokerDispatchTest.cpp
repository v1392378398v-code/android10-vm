#include "Broker.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

namespace a10binder {
class BrokerDispatchTest {
    static void require(bool passed, const char* name) {
        printf("CHECK\t%s\t%d\n", name, passed);
        if (!passed) exit(1);
    }

    static void prepare(Broker& broker) {
        broker.processes.emplace(1, Process{1, 2, getpid(), getuid()});
        broker.connections.emplace(2, Connection{-1, {}});
        broker.connections.at(2).process = 1;
        broker.connections.at(2).control = true;
        broker.connections.emplace(3, Connection{-1, {getpid(), getuid(), getgid()}});
        Connection& thread = broker.connections.at(3);
        Packet hello;
        hello.header.kind = Hello; hello.header.token = 1; hello.header.arg = gettid();
        broker.request(3, std::move(hello));
        require(thread.process == 1, "thread_registered");
        Packet enter;
        enter.header.kind = Command; enter.header.command = BC_ENTER_LOOPER;
        broker.request(3, std::move(enter));
        thread.output.clear();
        read(broker);
        Packet unrelated;
        unrelated.header.kind = Event;
        unrelated.header.command = BR_TRANSACTION;
        broker.processEvent(1, std::move(unrelated));
    }

    static void read(Broker& broker) {
        Packet packet;
        packet.header.kind = Read; packet.header.arg = 256;
        broker.request(3, std::move(packet));
    }

public:
    static void run() {
        {
            Broker broker;
            prepare(broker);
            Connection& thread = broker.connections.at(3);
            thread.readCapacity = 0;
            thread.looper = false;
            Packet packet;
            packet.header.kind = CommandRead;
            packet.header.command = BC_ENTER_LOOPER;
            packet.header.arg = 256;
            broker.request(3, std::move(packet));
            broker.dispatch();
            require(thread.output.size() == 2 && thread.output.front().header.kind == Ack &&
                    thread.output.front().header.status == 0 && thread.output.back().header.kind == Event &&
                    thread.readCapacity == 0 && broker.processes.at(1).queue.empty(),
                    "combined_write_ack_precedes_read_event");
        }
        {
            Broker broker;
            prepare(broker);
            Connection& thread = broker.connections.at(3);
            thread.readCapacity = 0;
            Packet packet;
            packet.header.kind = CommandRead;
            packet.header.command = 0;
            packet.header.arg = 256;
            broker.request(3, std::move(packet));
            broker.dispatch();
            require(thread.output.size() == 1 && thread.output.front().header.kind == Ack &&
                    thread.output.front().header.status != 0 && thread.readCapacity == 0 &&
                    broker.processes.at(1).queue.size() == 1,
                    "combined_write_error_keeps_read_event_pending");
        }
        {
            Broker broker;
            prepare(broker);
            Connection& thread = broker.connections.at(3);
            thread.readCapacity = 0;
            Packet packet;
            packet.header.kind = CommandRead;
            packet.header.command = BC_ENTER_LOOPER;
            packet.header.arg = 1;
            thread.looper = false;
            broker.request(3, std::move(packet));
            broker.dispatch();
            require(thread.output.size() == 2 && thread.output.front().header.status == 0 &&
                    thread.output.back().header.status == EMSGSIZE && thread.readCapacity == 0 &&
                    broker.processes.at(1).queue.size() == 1,
                    "combined_short_read_preserves_successful_write");
        }
        {
            Broker broker;
            prepare(broker);
            broker.connections.at(3).incoming.push_back(10);
            broker.dispatch();
            require(broker.connections.at(3).output.empty() && broker.processes.at(1).queue.size() == 1,
                    "busy_incoming_ignores_unrelated_transaction");
        }
        {
            Broker broker;
            prepare(broker);
            broker.connections.at(3).outgoing.push_back(10);
            broker.dispatch();
            require(broker.connections.at(3).output.empty() && broker.processes.at(1).queue.size() == 1,
                    "busy_outgoing_ignores_unrelated_transaction");
        }
        {
            Broker broker;
            prepare(broker);
            broker.dispatch();
            require(broker.connections.at(3).output.size() == 1 && broker.processes.at(1).queue.empty(),
                    "idle_looper_receives_process_transaction");
        }
        {
            Broker broker;
            prepare(broker);
            Connection& thread = broker.connections.at(3);
            thread.incoming.push_back(10);
            thread.outgoing.push_back(11);
            Packet nested;
            nested.header.kind = Event;
            nested.header.command = BR_TRANSACTION;
            broker.event(3, nested.header.command);
            broker.dispatch();
            require(thread.output.size() == 1 && broker.processes.at(1).queue.size() == 1,
                    "directed_nested_callback_still_delivered");
        }
        {
            Broker broker;
            prepare(broker);
            broker.dispatch();
            auto& thread = broker.connections.at(3);
            thread.output.clear();
            read(broker);
            broker.dispatch();
            require(thread.output.empty(), "empty_read_remains_parked");
            broker.event(3, BR_TRANSACTION_COMPLETE);
            broker.dispatch();
            require(thread.output.size() == 1 && thread.readCapacity == 0,
                    "event_wakes_parked_reader");
            thread.output.clear();
            read(broker);
            Packet packet;
            packet.header.kind = Event; packet.header.command = BR_TRANSACTION;
            broker.processEvent(1, std::move(packet));
            broker.dispatch();
            require(thread.output.size() == 1 && broker.processes.at(1).queue.empty(),
                    "process_event_wakes_parked_looper");
        }
        {
            Broker broker;
            prepare(broker);
            broker.calls.emplace(10, Call{3, 0, 1, 0, 0});
            broker.connections.at(3).outgoing.push_back(10);
            broker.dispatch();
            broker.finishCall(10);
            broker.dispatch();
            require(broker.connections.at(3).output.size() == 1 && broker.processes.at(1).queue.empty(),
                    "finished_call_unparks_process_dispatch");
        }
        {
            Broker broker;
            prepare(broker);
            broker.processes.at(1).maxThreads = 1;
            broker.dispatch();
            auto& thread = broker.connections.at(3);
            require(thread.output.size() == 1 && thread.output.front().header.command == BR_SPAWN_LOOPER &&
                    broker.processes.at(1).queue.size() == 1, "spawn_precedes_process_transaction");
            thread.output.clear();
            read(broker);
            broker.dispatch();
            require(thread.output.size() == 1 && thread.output.front().header.command == BR_TRANSACTION,
                    "spawn_pending_does_not_lose_transaction");
        }
        {
            Broker broker;
            prepare(broker);
            broker.connections.at(3).outgoing.push_back(10);
            broker.dispatch();
            auto& control = broker.connections.at(2);
            require(control.output.size() == 1 && control.output.front().header.kind == Wakeup,
                    "pending_process_notifies_control");
            control.output.clear();
            Packet rearm;
            rearm.header.kind = Rearm;
            broker.request(2, std::move(rearm));
            broker.dispatch();
            require(control.output.size() == 2 && control.output.back().header.kind == Wakeup,
                    "rearm_preserves_pending_readiness");
        }
    }
};
}

int main() { a10binder::BrokerDispatchTest::run(); return 0; }
