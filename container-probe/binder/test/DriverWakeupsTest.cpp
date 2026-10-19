#include "Driver.h"
#include "Wire.h"
#include <atomic>
#include <chrono>
#include <poll.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>

using namespace a10binder;

int main(int argc, char** argv) {
    if (argc != 2 && argc != 3) return 2;
    const bool combinedSupported = argc == 2;
    constexpr uint32_t commandReadKind = Rearm + 1;
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (strlen(argv[1]) >= sizeof(address.sun_path)) return 2;
    strcpy(address.sun_path, argv[1]);
    int listener = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) || listen(listener, 2)) return 2;
    std::atomic<int> commands{0}, rearms{0}, reads{0}, combinedReads{0};
    std::atomic<bool> peerOk{true};
    std::thread peer([&] {
        int sockets[2] = {-1, -1};
        for (int& socket : sockets) {
            socket = accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
            Packet hello, ack;
            ack.header.kind = Ack;
            ack.header.token = 1;
            ack.header.arg = combinedSupported ? 1 : 0;
            if (socket < 0 || !receivePacket(socket, &hello) || hello.header.kind != Hello ||
                !sendPacket(socket, ack)) { peerOk = false; break; }
        }
        bool pending = false;
        while (peerOk) {
            pollfd fds[] = {{sockets[0], POLLIN, 0}, {sockets[1], POLLIN, 0}};
            if (poll(fds, 2, 5000) <= 0) { peerOk = false; break; }
            bool closed = false;
            for (int i = 0; i < 2; ++i) {
                if (!(fds[i].revents & POLLIN)) continue;
                Packet request, reply;
                if (!receivePacket(sockets[i], &request)) { closed = true; break; }
                reply.header.kind = Ack;
                if (i == 1 && (request.header.kind == Command || request.header.kind == commandReadKind)) {
                    ++commands;
                    if (!pending) {
                        pending = true;
                        Packet wake;
                        wake.header.kind = Wakeup;
                        if (!sendPacket(sockets[0], wake)) { peerOk = false; break; }
                    }
                } else if (i == 1 && request.header.kind == Read) {
                    ++reads;
                    pending = false;
                    reply.header.kind = Event;
                    reply.header.command = BR_NOOP;
                } else if (i == 0 && request.header.kind == Rearm) {
                    ++rearms;
                } else { peerOk = false; break; }
                if (!sendPacket(sockets[i], reply)) { peerOk = false; break; }
                if (request.header.kind == commandReadKind) {
                    ++combinedReads;
                    pending = false;
                    Packet event;
                    event.header.kind = Event;
                    event.header.command = BR_NOOP;
                    if (!sendPacket(sockets[i], event)) { peerOk = false; break; }
                }
                if (i == 0 && pending) {
                    Packet wake;
                    wake.header.kind = Wakeup;
                    if (!sendPacket(sockets[0], wake)) { peerOk = false; break; }
                }
            }
            if (closed) break;
        }
        for (int socket : sockets) if (socket >= 0) close(socket);
    });
    int driver = a10binder_open(argv[1]);
    bool ok = driver >= 0;
    const uint32_t command = BC_EXIT_LOOPER;
    const auto started = std::chrono::steady_clock::now();
    for (int i = 0; i < 1000 && ok; ++i) {
        binder_write_read operation{};
        operation.write_buffer = reinterpret_cast<uintptr_t>(&command);
        operation.write_size = sizeof(command);
        ok = a10binder_ioctl(driver, BINDER_WRITE_READ, &operation) == 0 &&
             operation.write_consumed == sizeof(command) && operation.read_consumed == 0;
    }
    const auto micros = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now() - started).count();
    const int writeOnlyRearms = rearms;
    pollfd readiness{driver, POLLIN, 0};
    ok &= poll(&readiness, 1, 1000) == 1 && (readiness.revents & POLLIN);
    uint32_t event = 0;
    binder_write_read operation{};
    operation.write_buffer = reinterpret_cast<uintptr_t>(&command);
    operation.write_size = sizeof(command);
    operation.read_buffer = reinterpret_cast<uintptr_t>(&event);
    operation.read_size = sizeof(event);
    ok &= a10binder_ioctl(driver, BINDER_WRITE_READ, &operation) == 0 &&
          operation.write_consumed == sizeof(command) && operation.read_consumed == sizeof(event) && event == BR_NOOP;
    readiness.revents = 0;
    ok &= poll(&readiness, 1, 0) == 0;
    if (driver >= 0) a10binder_close(driver);
    peer.join();
    close(listener);
    unlink(argv[1]);
    printf("driver_write_only_commands=%d\ndriver_write_only_rearms=%d\n"
           "driver_read_rearms=%d\ndriver_combined_reads=%d\ndriver_separate_reads=%d\n"
           "driver_write_only_us=%lld\n", commands.load(), writeOnlyRearms,
           rearms.load() - writeOnlyRearms, combinedReads.load(), reads.load(), static_cast<long long>(micros));
    return ok && peerOk && commands == 1001 && reads == (combinedSupported ? 0 : 1) &&
           combinedReads == (combinedSupported ? 1 : 0) && writeOnlyRearms == 0 && rearms == 1 ? 0 : 7;
}
