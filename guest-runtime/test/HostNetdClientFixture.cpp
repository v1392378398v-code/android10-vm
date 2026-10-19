#include <errno.h>
#include <stdint.h>
#include <sys/types.h>
#include <unistd.h>

namespace {
bool matches(int fd, uint32_t tag, uid_t uid) {
    return fd == -1 && tag == 0x1234 && (uid == getuid() || uid == static_cast<uid_t>(-1));
}
}

extern "C" int tagSocket(int fd, uint32_t tag, uid_t uid) {
    return matches(fd, tag, uid) ? -EBADF : -EINVAL;
}

#ifdef HOST_HAS_TAG_WITH_PID
extern "C" int tagSocketWithPid(int fd, uint32_t tag, uid_t uid, pid_t pid) {
    return matches(fd, tag, uid) && pid == -1 ? -EACCES : -EINVAL;
}
#endif
