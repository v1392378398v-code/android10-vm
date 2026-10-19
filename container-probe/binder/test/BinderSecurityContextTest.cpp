#include "Broker.h"
#include "ClientBuffers.h"
#include "TransactionLayout.h"
#include <algorithm>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

namespace a10binder {
class BinderSecurityContextTest {
    static void require(bool value, const char* name) {
        if (!value) { fprintf(stderr, "FAIL: %s errno=%d\n", name, errno); exit(1); }
    }
public:
    static void run() {
        int sockets[2];
        require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets) == 0, "caller socket");
        char expected[4096]{};
        socklen_t length = sizeof(expected) - 1;
        require(getsockopt(sockets[0], SOL_SOCKET, SO_PEERSEC, expected, &length) == 0, "kernel peer context");
        Broker broker;
        broker.nextId = 100;
        broker.contextNode = 10;
        broker.processes.emplace(1, Process{1, 3, getpid(), getuid()});
        broker.processes.emplace(2, Process{2, 4, getpid(), getuid()});
        broker.processes.at(2).guestUid = 2000;
        broker.connections.emplace(3, Connection{sockets[1], {}});
        broker.connections.at(3).process = 1;
        broker.connections.emplace(4, Connection{sockets[0], {}});
        broker.connections.at(4).process = 2;
        broker.nodes.emplace(10, Node{10, 2, 4, 0, 0, FLAT_BINDER_FLAG_ACCEPTS_FDS});
        flat_binder_object service{};
        service.hdr.type = BINDER_TYPE_BINDER;
        service.flags = FLAT_BINDER_FLAG_TXN_SECURITY_CTX | FLAT_BINDER_FLAG_ACCEPTS_FDS;
        service.binder = 0x1110;
        service.cookie = 0x2220;
        binder_size_t offset = 0;
        binder_transaction_data registration{};
        registration.code = 3;
        registration.data_size = sizeof(service);
        registration.offsets_size = sizeof(offset);
        registration.data.ptr.buffer = reinterpret_cast<uintptr_t>(&service);
        registration.data.ptr.offsets = reinterpret_cast<uintptr_t>(&offset);
        Packet request;
        require(serializeTransaction(BC_TRANSACTION, registration, &request), "DRM registration parcel");
        require(broker.transact(3, std::move(request)) == 0, "register SID requesting DRM service");
        auto& managerQueue = broker.processes.at(2).queue;
        require(!managerQueue.empty(), "service manager registration event");
        flat_binder_object handle;
        require(managerQueue.back().get(sizeof(registration), &handle) && handle.hdr.type == BINDER_TYPE_HANDLE,
                "DRM service handle");
        binder_transaction_data call{};
        call.target.handle = handle.handle;
        call.code = 1;
        call.flags = TF_ONE_WAY;
        Packet message;
        require(serializeTransaction(BC_TRANSACTION, call, &message), "DRM caller parcel");
        require(broker.transact(4, std::move(message)) == 0, "DRM call with kernel caller context");
        auto& queue = broker.processes.at(1).queue;
        auto event = std::find_if(queue.begin(), queue.end(), [](const Packet& packet) {
            return packet.header.command == BR_TRANSACTION_SEC_CTX;
        });
        require(event != queue.end(), "security context transaction event");
        binder_transaction_data decoded;
        binder_uintptr_t security = 0;
        require(clientBuffers().receive(&*event, &decoded, &security), "map caller context into read-only transaction buffer");
        require(decoded.sender_euid == 2000 && security &&
                strcmp(reinterpret_cast<const char*>(security), expected) == 0, "real peer context and guest UID preserved");
        TransactionLayout layout;
        Packet malformed;
        malformed.header = event->header;
        malformed.data = event->data;
        malformed.data.back() = 'x';
        require(!validateTransaction(malformed, &layout), "reject unterminated caller context");
        clientBuffers().release(decoded.data.ptr.buffer);
        close(sockets[0]);
        close(sockets[1]);
        puts("binder_drm_sid_registration=1\nbinder_kernel_peer_context=1\nbinder_context_buffer_lifetime=1");
    }
};
}

int main() { a10binder::BinderSecurityContextTest::run(); }
