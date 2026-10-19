#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    register long result asm("x0") = AT_FDCWD;
    register const char* path asm("x1") = argv[1];
    register long flags asm("x2") = O_RDONLY | O_NOFOLLOW | O_CLOEXEC;
    register long mode asm("x3") = 0;
    register long number asm("x8") = __NR_openat;
    asm volatile("svc #0" : "+r"(result) : "r"(path), "r"(flags), "r"(mode), "r"(number)
                 : "memory", "cc");
    if (result < 0) {
        fprintf(stderr, "raw_apk_open_errno=%ld path=%s\n", -result, argv[1]);
        return 1;
    }
    char header[4];
    bool passed = read(result, header, sizeof(header)) == sizeof(header) &&
            !memcmp(header, "PK\003\004", sizeof(header));
    close(result);
    printf("raw_apk_contents=%d\n", passed);
    return passed ? 0 : 1;
}
