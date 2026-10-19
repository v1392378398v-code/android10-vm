#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/system_properties.h>
#include <unistd.h>

static int describe_elf(struct dl_phdr_info *info, size_t size, void *data) {
    (void) size;
    (void) data;
    printf("elf=%s\n", info->dlpi_name);
    return 0;
}

static int describe_status(void) {
    FILE *status = fopen("/proc/self/status", "r");
    if (!status) return -1;
    char line[512];
    int found = 0;
    while (fgets(line, sizeof(line), status)) {
        unsigned long long caps;
        if (sscanf(line, "CapEff: %llx", &caps) == 1) {
            printf("cap_eff=%016llx\n", caps);
            found = 1;
        }
    }
    fclose(status);
    return found ? 0 : -1;
}

int main(int argc, char **argv) {
    pid_t parent = getppid();
    if (parent == 1 || prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != parent) return 70;
    if (argc != 2) return 64;
    printf("nonce=%s\nuid=%u\neuid=%u\npage_size=%ld\n", argv[1],
           (unsigned) getuid(), (unsigned) geteuid(), sysconf(_SC_PAGESIZE));
    Dl_info program, libc;
    if (!dladdr((void *) main, &program) || !dladdr((void *) getpid, &libc)) return 71;
    printf("program=%s\nlibc=%s\n", program.dli_fname, libc.dli_fname);
    if (describe_status()) return 72;
    FILE *label = fopen("/proc/self/attr/current", "r");
    if (label) {
        char context[256];
        if (fgets(context, sizeof(context), label)) printf("selinux=%s\n", context);
        fclose(label);
    }
    char sdk[PROP_VALUE_MAX] = {0};
    __system_property_get("ro.build.version.sdk", sdk);
    printf("visible_sdk=%s\n", sdk);
    double sine = sin((double) (unsigned char) argv[1][0]);
    printf("math_ok=%d\n", isfinite(sine) && fabs(sine) <= 1.0);
    dl_iterate_phdr(describe_elf, NULL);
    void *host_log = dlopen("liblog.so", RTLD_NOW | RTLD_LOCAL);
    printf("host_liblog_loaded=%d\n", host_log != NULL);
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return 73;
    char line[2048];
    while (fgets(line, sizeof(line), maps)) printf("MAP\t%s", line);
    fclose(maps);
    if (host_log) dlclose(host_log);
    puts("probe_complete=1");
    return 0;
}
