#include <errno.h>
#include <grp.h>
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static bool check(bool passed, const char* name, unsigned id) {
    printf("CHECK\t%s\t%u\t%d\n", name, id, passed);
    return passed;
}

static bool account(unsigned id, const char* name, bool exists) {
    bool passed = true;
    const char* shell = !strncmp(name, "oem_", 4) ? "/vendor/bin/sh" : "/system/bin/sh";
    passwd* pw = getpwuid(id);
    passed &= check(exists ? pw && pw->pw_uid == id && pw->pw_gid == id &&
                    !strcmp(pw->pw_name, name) && !strcmp(pw->pw_dir, "/") &&
                    !strcmp(pw->pw_shell, shell) : !pw, "passwd_id", id);
    pw = getpwnam(name);
    passed &= check(exists ? pw && pw->pw_uid == id : !pw, "passwd_name", id);
    group* gr = getgrgid(id);
    passed &= check(exists ? gr && gr->gr_gid == id && !strcmp(gr->gr_name, name) : !gr,
                    "group_id", id);
    gr = getgrnam(name);
    passed &= check(exists ? gr && gr->gr_gid == id : !gr, "group_name", id);
    passwd result{}, *found = nullptr;
    char buffer[128];
    errno = EBUSY;
    int status = getpwuid_r(id, &result, buffer, sizeof(buffer), &found);
    passed &= check(status == 0 && errno == EBUSY && (exists ? found == &result &&
                    result.pw_uid == id && !strcmp(result.pw_name, name) : !found), "passwd_r", id);
    if (exists) {
        found = nullptr;
        passed &= check(getpwnam_r(name, &result, buffer, sizeof(buffer), &found) == 0 &&
                        found && found->pw_uid == id, "passwd_name_r", id);
        found = nullptr;
        passed &= check(getpwuid_r(id, &result, buffer, 1, &found) == ERANGE && !found,
                        "passwd_r_small_buffer", id);
    }
    return passed;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    bool legacy = !strcmp(argv[1], "legacy");
    bool passed = account(0, "root", true) && account(1000, "system", true) &&
                  account(3003, "inet", true) && account(9997, "everybody", true) &&
                  account(9999, "nobody", true);
    const unsigned ids[] = {2900, 2999, 5000, 5999, 3000, 4999, 6000, 9801, 9802, 9996};
    for (unsigned id : ids) {
        char name[32];
        snprintf(name, sizeof(name), "oem_%u", id);
        bool standard = (id >= 2900 && id <= 2999) || (id >= 5000 && id <= 5999);
        passed &= account(id, name, standard || legacy);
    }
    passed &= account(2899, "oem_2899", false);
    passed &= check(getuid() == 9802 && geteuid() == 9802 && syscall(__NR_getuid) >= 10000,
                    "kernel_identity_preserved", 9802);
    printf("oem_accounts_complete=%d\n", passed);
    return passed ? 0 : 1;
}
