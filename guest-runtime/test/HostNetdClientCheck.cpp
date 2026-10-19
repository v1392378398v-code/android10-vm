#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    using TagWithPid = int (*)(int, uint32_t, uid_t, pid_t);
    auto tag = reinterpret_cast<TagWithPid>(dlsym(library, "tagSocketWithPid"));
    if (!tag) { fprintf(stderr, "Missing MIUI dynamic export: tagSocketWithPid\n"); return 1; }
    const bool hasPid = strcmp(argv[2], "pid") == 0;
    const int expected = hasPid ? -EACCES : -EBADF;
    if (tag(-1, 0x1234, 1000, -1) != expected ||
            tag(-1, 0x1234, static_cast<uid_t>(-1), -1) != expected) {
        fprintf(stderr, "Socket tag arguments or host error changed\n");
        return 1;
    }
    puts(hasPid ? "netd_tag_with_pid_forward=1" : "netd_tag_without_pid_forward=1");
    dlclose(library);
    return 0;
}
