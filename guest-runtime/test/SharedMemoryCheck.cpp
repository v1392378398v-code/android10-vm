#include "../native/HostDeviceTransport.h"
#include <cutils/ashmem.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/memfd.h>
#include <pthread.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>

namespace {
bool brokerRequired;
bool brokerUsed;
bool fragmentedReply;

void require(bool value, const char* name) {
    printf("shared_memory_%s=%s\n", name, value ? "passed" : "failed");
    if (!value) exit(1);
}

void* serve(void* value) {
    int fd = accept(*static_cast<int*>(value), nullptr, nullptr);
    uint32_t header[5]{};
    require(fd >= 0 && recv(fd, header, sizeof(header), MSG_WAITALL) == sizeof(header), "broker_request");
    require(ntohl(header[0]) == 0x4131304d && ntohl(header[1]) == 1 && ntohl(header[2]) == 1 &&
            ntohl(header[3]) == 4096 && ntohl(header[4]) == 10, "broker_arguments");
    char name[10];
    require(recv(fd, name, sizeof(name), MSG_WAITALL) == sizeof(name) &&
            !memcmp(name, "regression", sizeof(name)), "broker_name");
    int shared = syscall(__NR_memfd_create, "a10vm-test-host-memory", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    require(shared >= 0 && ftruncate(shared, 4096) == 0, "broker_region");
    int32_t result = 0;
    size_t first = fragmentedReply ? 1 : sizeof(result);
    iovec data{&result, first};
    alignas(cmsghdr) char control[CMSG_SPACE(sizeof(int))]{};
    msghdr message{};
    message.msg_iov = &data; message.msg_iovlen = 1;
    message.msg_control = control; message.msg_controllen = sizeof(control);
    cmsghdr* ancillary = CMSG_FIRSTHDR(&message);
    ancillary->cmsg_level = SOL_SOCKET; ancillary->cmsg_type = SCM_RIGHTS;
    ancillary->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(ancillary), &shared, sizeof(shared));
    require(sendmsg(fd, &message, MSG_NOSIGNAL) == static_cast<ssize_t>(first), "broker_descriptor");
    if (fragmentedReply)
        require(send(fd, reinterpret_cast<char*>(&result) + first, sizeof(result) - first, MSG_NOSIGNAL) ==
                static_cast<ssize_t>(sizeof(result) - first), "broker_fragment");
    close(shared); close(fd);
    brokerUsed = true;
    return nullptr;
}
}

extern "C" int __real_fcntl(int, int, ...);
extern "C" int __wrap_fcntl(int fd, int operation, ...) {
    va_list values;
    va_start(values, operation);
    int argument = (operation == F_ADD_SEALS) ? va_arg(values, int) : 0;
    va_end(values);
    if (brokerRequired && operation == F_ADD_SEALS && argument == 0x0010) {
        char path[64], name[256];
        snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
        ssize_t size = readlink(path, name, sizeof(name) - 1);
        if (size > 0) {
            name[size] = '\0';
            if (strstr(name, "a10vm-seal-probe")) { errno = EINVAL; return -1; }
        }
    }
    return operation == F_ADD_SEALS ? __real_fcntl(fd, operation, argument) : __real_fcntl(fd, operation);
}

int main(int argc, char** argv) {
    setbuf(stdout, nullptr);
    bool external = argc > 2 && !strcmp(argv[1], "bridge");
    fragmentedReply = argc > 1 && !strcmp(argv[1], "fragmented");
    brokerRequired = external || fragmentedReply || (argc > 1 && !strcmp(argv[1], "legacy"));
    char temporary[] = "/data/data/com.termux/files/usr/tmp/shared-memory-XXXXXX";
    const char* directory = external ? argv[2] : mkdtemp(temporary);
    require(directory != nullptr, "directory");
    setenv("A10VM_ROOTFS", directory, 1);
    setenv("A10VM_STATE_ROOT", directory, 1);
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s/shared-memory.sock", directory);
    int listener = -1;
    pthread_t server;
    if (!external) {
        listener = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        require(listener >= 0 && bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 &&
                listen(listener, 1) == 0, "listener");
        if (brokerRequired) require(pthread_create(&server, nullptr, serve, &listener) == 0, "server");
    }
    int fd = ashmem_create_region("regression", 4096);
    require(fd >= 0 && ashmem_valid(fd) && ashmem_get_size_region(fd) == 4096, "create");
    require((fcntl(fd, F_GETFD) & FD_CLOEXEC) != 0, "cloexec");
    auto* writer = static_cast<unsigned*>(mmap(nullptr, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0));
    require(writer != MAP_FAILED, "writer");
    *writer = 0x4131304d;
    require(ashmem_set_prot_region(fd, PROT_READ) == 0, "readonly_with_existing_writer");
    auto* reader = static_cast<unsigned*>(mmap(nullptr, 4096, PROT_READ, MAP_SHARED, fd, 0));
    require(reader != MAP_FAILED && *reader == 0x4131304d, "roundtrip");
    *writer = 0x4131304e;
    require(*reader == 0x4131304e, "existing_writer_retained");
    errno = 0;
    require(mmap(nullptr, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0) == MAP_FAILED &&
            (errno == EPERM || errno == EACCES), "new_writer_blocked");
    require(ashmem_set_prot_region(fd, PROT_READ | PROT_WRITE) < 0, "write_protection_monotonic");
    munmap(writer, 4096); munmap(reader, 4096); close(fd);
    if (!external) {
        if (brokerRequired) pthread_join(server, nullptr);
        require(brokerUsed == brokerRequired, "capability_route");
        close(listener); unlink(address.sun_path); rmdir(directory);
    }
}
