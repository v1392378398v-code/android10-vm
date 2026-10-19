#include "ProbeOutput.h"
#include <errno.h>
#include <fcntl.h>

static bool readLine(int fd, char* text, size_t capacity) {
    size_t count = 0;
    while (count + 1 < capacity) {
        char ch;
        ssize_t size = TEMP_FAILURE_RETRY(read(fd, &ch, 1));
        if (size != 1) break;
        if (ch == '\n' || ch == '\0') break;
        text[count++] = ch;
    }
    text[count] = '\0';
    return count != 0;
}

bool printIdentity(const char* nonce) {
    emit("nonce=%s\npid=%d\nuid=%d\neuid=%d\npage_size=%d\n",
         nonce, getpid(), getuid(), geteuid(), getpagesize());
    const char* paths[] = {"/proc/self/status", "/proc/self/attr/current", "/proc/self/maps"};
    bool passed = true;
    for (int index = 0; index < 3; ++index) {
        int fd = open(paths[index], O_RDONLY | O_CLOEXEC);
        if (fd == -1) return check(false, "bootstrap_identity_files");
        bool found = false;
        char line[2048];
        while (readLine(fd, line, sizeof(line))) {
            if (index == 0 && strncmp(line, "CapEff:", 7) == 0) {
                const char* value = line + 7;
                while (*value == ' ' || *value == '\t') ++value;
                found = emit("cap_eff=%s\n", value);
            } else if (index == 1) {
                found = emit("selinux=%s\n", line);
            } else if (index == 2) {
                found = emit("MAP\t%s\n", line);
            }
        }
        close(fd);
        passed &= found;
    }
    return check(passed, "bootstrap_identity_files");
}
