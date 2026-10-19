#include "Wire.h"
#include <cstdio>
#include <cstdlib>
#include <cerrno>
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>

using namespace a10binder;

static void require(bool condition, const char* operation) {
    if (!condition) { std::perror(operation); std::exit(1); }
}

int main() {
    int sockets[2];
    require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets) == 0, "socketpair");
    for (size_t count : {size_t(40), kMaxFds}) {
      for (size_t bytes : {size_t(16), kInlinePacket + 1}) {
        Packet input, output;
        input.data.assign(bytes, 0x61);
        // Chromium passes its mapped files as one Binder parcel, not separate calls.
        for (size_t n = 0; n < count; ++n) {
            int fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
            require(fd >= 0, "open mapped file");
            input.fds.push_back(fd);
        }
        require(sendPacket(sockets[0], input), "Chromium mapped-file parcel send");
        require(receivePacket(sockets[1], &output), "Chromium mapped-file parcel receive");
        require(output.fds.size() == count && output.data == input.data, "mapped files roundtrip");
        for (int fd : output.fds) require(fcntl(fd, F_GETFD) & FD_CLOEXEC, "received file CLOEXEC");
      }
    }
    Packet excessive;
    for (size_t n = 0; n <= kMaxFds; ++n) {
        int fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
        require(fd >= 0, "open over-limit file");
        excessive.fds.push_back(fd);
    }
    require(!sendPacket(sockets[0], excessive) && errno == EMSGSIZE, "FD limit enforced");
    close(sockets[0]); close(sockets[1]);
    std::puts("PASS: Chromium mapped-file parcels (40/128 FDs, inline/shared, CLOEXEC, bounded limit)");
}
