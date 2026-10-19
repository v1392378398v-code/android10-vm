#include "Probe.h"
#include <dlfcn.h>
#include <stdexcept>

bool lateExceptionChecks(const char* path) {
    bool passed = true;
    for (int round = 0; round < 2; ++round) {
        void* module = dlopen(path, RTLD_NOW | RTLD_LOCAL);
        if (!check(module != nullptr, "exception_late_dlopen")) return false;
        auto function = reinterpret_cast<void (*)(int*)>(dlsym(module, "lateThrow"));
        if (!check(function != nullptr, "exception_late_dlsym")) { dlclose(module); return false; }
        int destroyed = 0;
        bool caught = false;
        try { function(&destroyed); }
        catch (const std::runtime_error& error) { caught = !strcmp(error.what(), "android10-late-exception"); }
        passed &= check(caught && destroyed == 1, "exception_late_dso_raii");
        passed &= check(dlclose(module) == 0, "exception_late_dlclose");
        void* resident = dlopen(path, RTLD_NOW | RTLD_NOLOAD);
        passed &= check(resident == nullptr, "exception_late_dso_unloaded");
        if (resident) dlclose(resident);
    }
    emit("exception_late_rounds=2\n");
    return passed;
}
