#include "Probe.h"
#include <dlfcn.h>
#include <exception>
#include <math.h>
#include <signal.h>
#include <stdexcept>
#include <stdlib.h>
#include <string>
#include <sys/prctl.h>
#include <sys/system_properties.h>
#include <vector>

static std::string constructor_text("android10-runtime");
static std::vector<int> constructor_values{10, 29};

static void terminateHandler() { emit("terminate_handler_called=1\n"); _Exit(86); }
__attribute__((noinline)) static void raiseException() { throw std::runtime_error("termination-test"); }
__attribute__((noinline)) static void failNoexcept() noexcept { raiseException(); }
__attribute__((destructor)) static void finish() { emit("companion_fini_complete=1\n"); }

int main(int argc, char** argv) {
    if (argc != 4) return 64;
    pid_t parent = getppid();
    if (parent == 1 || prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != parent) return 70;
    emit("companion_mode=%s\n", argv[1]);
    if (!strcmp(argv[1], "uncaught") || !strcmp(argv[1], "noexcept")) {
        std::set_terminate(terminateHandler);
        if (!strcmp(argv[1], "noexcept")) failNoexcept();
        raiseException();
    }
    if (strcmp(argv[1], "normal")) return 64;
    char sdk[PROP_VALUE_MAX]{};
    __system_property_get("ro.build.version.sdk", sdk);
    emit("main_sdk=%s\nlibcpp_version=%d\n", sdk, _LIBCPP_VERSION);
    bool passed = check(!strcmp(sdk, "29"), "companion_private_sdk29");
    passed &= check(constructor_text == "android10-runtime" && constructor_values.size() == 2 &&
                    constructor_values[1] == 29, "cxx_global_constructors");
    Dl_info libc{}, math{}, cxx{};
    bool found = dladdr(reinterpret_cast<void*>(&getpid), &libc) &&
                 dladdr(reinterpret_cast<void*>(static_cast<double (*)(double)>(&sin)), &math) &&
                 dladdr(reinterpret_cast<void*>(&std::set_terminate), &cxx);
    emit("source_libc=%s\nsource_libm=%s\nsource_cxx=%s\n",
         found ? libc.dli_fname : "", found ? math.dli_fname : "", found ? cxx.dli_fname : "");
    passed &= check(found && libc.dli_fbase != math.dli_fbase && libc.dli_fbase != cxx.dli_fbase &&
                    math.dli_fbase != cxx.dli_fbase, "companion_distinct_libraries");
    passed &= mathChecks();
    passed &= complexChecks();
    passed &= cxxChecks();
    passed &= exceptionChecks();
    passed &= lateExceptionChecks(argv[3]);
    passed &= unwindChecks();
    passed &= printIdentity(argv[2]);
    emit("companion_complete=%d\n", passed);
    return passed ? 0 : 1;
}
