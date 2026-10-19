#include <errno.h>
#include <grp.h>
#include <linux/capability.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>

int capset(cap_user_header_t, const cap_user_data_t);
int capget(cap_user_header_t, cap_user_data_t);

int main(void) {
    uid_t host = syscall(__NR_getuid);
    if (host < 10000 || getuid() != 0) return 1;
    gid_t wanted[] = {1007, 2000, 1028, 1015}, actual[4];
    if (setgroups(4, wanted) || getgroups(4, actual) != 4) return 2;
    for (int i = 0; i < 4; ++i) if (wanted[i] != actual[i]) return 3;
    if (setgid(1000) || setuid(1000) || getuid() != 1000 || geteuid() != 1000 || getgid() != 1000) return 4;
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct wanted_caps[2] = {{1u << 7, 1u << 7, 0}, {0, 0, 0}}, actual_caps[2];
    if (capset(&header, wanted_caps) || capget(&header, actual_caps) || actual_caps[0].effective != (1u << 7)) return 5;
    if (syscall(__NR_getuid) != host || syscall(__NR_capget, &header, actual_caps) ||
        actual_caps[0].effective || actual_caps[1].effective) return 6;
    errno = 0;
    if (setgroups(65537, wanted) != -1 || errno != EINVAL) return 7;
    printf("rom_service_identity_ready=1\nhost_uid=%u\nhost_cap_eff=0\nguest_uid=%u\n", host, getuid());
    return 0;
}
