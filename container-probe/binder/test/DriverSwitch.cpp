#include "Driver.h"
#include <errno.h>
#include <sys/types.h>
#include <sys/epoll.h>
#include <sys/wait.h>
#include <unistd.h>
#include <linux/android/binder.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace probe {
static bool queueReply(int fd) {
    uint8_t bytes[sizeof(uint32_t) + sizeof(binder_transaction_data)]{};
    uint32_t command = BC_TRANSACTION;
    binder_transaction_data transaction{};
    transaction.target.handle = 9999;
    memcpy(bytes, &command, sizeof(command));
    memcpy(bytes + sizeof(command), &transaction, sizeof(transaction));
    binder_write_read operation{};
    operation.write_buffer = reinterpret_cast<uintptr_t>(bytes);
    operation.write_size = sizeof(bytes);
    return a10binder_ioctl(fd, BINDER_WRITE_READ, &operation) == 0 &&
           operation.write_consumed == sizeof(bytes);
}

static bool readReply(int fd) {
    uint32_t command = 0;
    binder_write_read operation{};
    operation.read_buffer = reinterpret_cast<uintptr_t>(&command);
    operation.read_size = sizeof(command);
    return a10binder_ioctl(fd, BINDER_WRITE_READ, &operation) == 0 &&
           operation.read_consumed == sizeof(command) && command == BR_DEAD_REPLY;
}

int driverSwitch(const char* binder, const char* hardware) {
    if (!hardware) return 2;
    int first = a10binder_open(binder), second = a10binder_open(hardware);
    if (first < 0 || second < 0) return 3;
    bool passed = true;
    uint32_t threads = 64;
    passed &= a10binder_ioctl(second, BINDER_SET_MAX_THREADS, &threads) == 0;
    threads = 65;
    passed &= a10binder_ioctl(second, BINDER_SET_MAX_THREADS, &threads) == -1 && errno == EINVAL;
    for (int round = 0; round < 64 && passed; ++round)
        passed = queueReply(first) && queueReply(second) && readReply(first) && readReply(second);
    passed &= a10binder_close(first) == 0;
    passed = passed && queueReply(second) && readReply(second);
    passed &= a10binder_close(second) == 0;
    printf("binder_driver_switch_complete=%d\n", passed);
    return passed ? 0 : 3;
}

int driverPolling(const char* binder) {
    int driver = a10binder_open(binder), epoll = epoll_create1(EPOLL_CLOEXEC);
    if (driver < 0 || epoll < 0) return 3;
    epoll_event event{};
    event.events = EPOLLIN;
    event.data.fd = driver;
    bool passed = epoll_ctl(epoll, EPOLL_CTL_ADD, driver, &event) == 0;
    for (int round = 0; round < 8 && passed; ++round) {
        passed = queueReply(driver) && epoll_wait(epoll, &event, 1, 500) == 1 &&
                 event.data.fd == driver && readReply(driver) && epoll_wait(epoll, &event, 1, 10) == 0;
    }
    for (int round = 0; round < 8 && passed; ++round) {
        for (int queued = 0; queued < 4 && passed; ++queued) passed = queueReply(driver);
        for (int queued = 0; queued < 4 && passed; ++queued)
            passed = epoll_wait(epoll, &event, 1, 500) == 1 &&
                     event.data.fd == driver && readReply(driver);
        passed &= epoll_wait(epoll, &event, 1, 10) == 0;
    }
    passed &= a10binder_close(driver) == 0;
    close(epoll);
    printf("binder_driver_polling_complete=%d\n", passed);
    return passed ? 0 : 3;
}

int driverForkClose(const char* binder) {
    int driver = a10binder_open(binder);
    if (driver < 0 || !queueReply(driver) || !readReply(driver)) return 3;
    pid_t child = fork();
    if (child == 0) {
        int status = a10binder_is_driver(driver) ? a10binder_close(driver) : close(driver);
        _exit(status == 0 ? 0 : 3);
    }
    int status = 0;
    bool passed = child > 0 && waitpid(child, &status, 0) == child &&
                  WIFEXITED(status) && WEXITSTATUS(status) == 0;
    passed = passed && queueReply(driver) && readReply(driver);
    a10binder_close(driver);
    printf("binder_driver_fork_close_complete=%d\n", passed);
    return passed ? 0 : 3;
}
}
