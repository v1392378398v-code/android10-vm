#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

static int rawOpen(const char* path) {
    register long number asm("x8") = __NR_openat;
    register long directory asm("x0") = AT_FDCWD;
    register const char* name asm("x1") = path;
    register long flags asm("x2") = O_RDONLY | O_CLOEXEC;
    register long mode asm("x3") = 0;
    asm volatile("svc #0" : "+r"(directory) : "r"(number), "r"(name), "r"(flags), "r"(mode) : "memory", "cc");
    return directory < 0 ? -1 : directory;
}

static bool row(int descriptor, uintptr_t address, char* output, size_t capacity) {
    FILE* stream = fdopen(descriptor, "r");
    if (!stream) { close(descriptor); return false; }
    char line[8192];
    bool found = false;
    while (fgets(line, sizeof(line), stream)) {
        unsigned long start, end;
        if (sscanf(line, "%lx-%lx", &start, &end) == 2 && start <= address && address < end) {
            strlcpy(output, line, capacity);
            found = true;
            break;
        }
    }
    fclose(stream);
    return found;
}

static bool sameHeader(const char* first, const char* second) {
    const char* a = strchr(first, '/');
    const char* b = strchr(second, '/');
    return a && b && a - first == b - second && !memcmp(first, second, a - first);
}

static bool check(bool passed, const char* name) {
    printf("%s=%d\n", name, passed);
    return passed;
}

int main(int argc, char** argv) {
    void* art = dlopen("libart.so", RTLD_NOW);
    if (!art) { fprintf(stderr, "ART load: %s\n", dlerror()); return 1; }
    void* symbol = dlsym(art, "JNI_CreateJavaVM");
    Dl_info info{};
    if (!symbol || !dladdr(symbol, &info) || !info.dli_fname) return 1;
    printf("art_library=%s\n", info.dli_fname);
    bool passed = true;
    if (argc == 3) {
        void* loader = dlopen(argv[1], RTLD_NOW);
        void* entry = loader ? dlsym(loader, "Java_com_hooker_lsplant_HookMain_nInit") : nullptr;
        Dl_info plugin{};
        if (!entry || !dladdr(entry, &plugin)) {
            fprintf(stderr, "Hook loader: %s\n", dlerror()); return 1;
        }
        auto locate = reinterpret_cast<bool (*)()>(reinterpret_cast<uintptr_t>(plugin.dli_fbase)
                + strtoull(argv[2], nullptr, 16));
        passed &= check(locate(), "lsplant_art_located");
    }
    char raw[8192]{}, mapped[8192]{}, direct[8192]{}, relative[8192]{}, threaded[8192]{};
    uintptr_t address = reinterpret_cast<uintptr_t>(symbol);
    passed &= check(row(rawOpen("/proc/self/maps"), address, raw, sizeof(raw)), "maps_kernel_art");
    int descriptor = open("/proc/self/maps", O_RDONLY | O_CLOEXEC);
    passed &= check(descriptor >= 0 && (fcntl(descriptor, F_GETFL) & O_ACCMODE) == O_RDONLY
            && (fcntl(descriptor, F_GETFD) & FD_CLOEXEC), "maps_descriptor_flags");
    passed &= check(row(descriptor, address, mapped, sizeof(mapped))
            && strstr(mapped, info.dli_fname), "maps_matches_dladdr");
    passed &= check(sameHeader(raw, mapped), "maps_header_unchanged");
    passed &= check(row(syscall(__NR_openat, AT_FDCWD, "/proc/self/maps", O_RDONLY, 0),
            address, direct, sizeof(direct)) && strstr(direct, info.dli_fname), "maps_syscall_open");
    int directory = open("/proc/self", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    passed &= check(row(openat(directory, "maps", O_RDONLY), address, relative, sizeof(relative))
            && strstr(relative, info.dli_fname), "maps_relative_open");
    close(directory);
    passed &= check(row(open("/proc/thread-self/maps", O_RDONLY), address, threaded, sizeof(threaded))
            && strstr(threaded, info.dli_fname), "maps_thread_self");

    const char* apk = "/data/local/tmp/maps fixture.apk";
    int file = open(apk, O_CREAT | O_RDWR | O_TRUNC | O_CLOEXEC, 0600);
    if (file < 0 || ftruncate(file, 4096) != 0) return 1;
    void* page = mmap(nullptr, 4096, PROT_READ, MAP_PRIVATE, file, 0);
    close(file);
    if (page == MAP_FAILED) return 1;
    address = reinterpret_cast<uintptr_t>(page);
    passed &= check(row(rawOpen("/proc/self/maps"), address, raw, sizeof(raw))
            && row(open("/proc/self/maps", O_RDONLY), address, mapped, sizeof(mapped))
            && sameHeader(raw, mapped) && strchr(mapped, '/')
            && !strncmp(strchr(mapped, '/'), apk, strlen(apk))
            && strchr(mapped, '/')[strlen(apk)] == '\n', "maps_guest_apk_with_spaces");
    munmap(page, 4096);
    unlink(apk);
    dlclose(art);
    return passed ? 0 : 1;
}
