#include "Driver.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/android/binder.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
thread_local bool insideDriver;
struct DriverCall {
    DriverCall() { insideDriver = true; }
    ~DriverCall() { insideDriver = false; }
};

const char* device(const char* path) {
    if (!path || insideDriver) return nullptr;
    if (!strcmp(path, "/dev/binder")) return a10binder_default_driver();
    if (!strcmp(path, "/dev/hwbinder")) return a10binder_default_hwbinder_driver();
    return nullptr;
}

int openDevice(const char* path, int flags, mode_t mode) {
    const char* endpoint = device(path);
    if (!endpoint) return openat(AT_FDCWD, path, flags, mode);
    if ((flags & O_ACCMODE) != O_RDWR) { errno = EINVAL; return -1; }
    DriverCall call;
    return a10binder_open(endpoint);
}
}

extern "C" int open(const char* path, int flags, ...) {
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, int);
        va_end(args);
    }
    return openDevice(path, flags, mode);
}

extern "C" int __open_2(const char* path, int flags) {
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { errno = EINVAL; return -1; }
    return openDevice(path, flags, 0);
}

extern "C" int access(const char* path, int mode) {
    const char* endpoint = device(path);
    return faccessat(AT_FDCWD, endpoint ? endpoint : path, mode, 0);
}

extern "C" int ioctl(int fd, int request, ...) {
    va_list args;
    va_start(args, request);
    void* argument = va_arg(args, void*);
    va_end(args);
    if (!insideDriver && a10binder_is_driver(fd)) {
        DriverCall call;
        int result = a10binder_ioctl(fd, static_cast<unsigned int>(request), argument);
        if (result == 0 && static_cast<unsigned int>(request) == BINDER_SET_CONTEXT_MGR) {
            printf("binder_context_pid=%d\nbinder_context_ready=1\n", getpid());
            fflush(stdout);
        }
        return result;
    }
    return syscall(__NR_ioctl, fd, static_cast<unsigned int>(request), argument);
}

extern "C" int close(int fd) {
    if (!insideDriver && a10binder_is_driver(fd)) {
        DriverCall call;
        return a10binder_close(fd);
    }
    return syscall(__NR_close, fd);
}

extern "C" void* mmap(void* address, size_t size, int protection, int flags, int fd, off_t offset) {
    // Anonymous allocator maps must never acquire the Binder metadata lock.
    if (fd >= 0 && !(flags & MAP_ANONYMOUS) && !insideDriver && a10binder_is_driver(fd)) {
        if (offset || (protection & PROT_WRITE)) { errno = EINVAL; return MAP_FAILED; }
        protection = PROT_NONE;
        flags = (flags & ~MAP_SHARED) | MAP_PRIVATE | MAP_ANONYMOUS;
        fd = -1;
    }
    return reinterpret_cast<void*>(syscall(__NR_mmap, address, size, protection, flags, fd, offset));
}

extern "C" void* mmap64(void* address, size_t size, int protection, int flags, int fd, off64_t offset) {
    return mmap(address, size, protection, flags, fd, offset);
}
