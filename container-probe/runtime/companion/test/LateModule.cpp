#include "Probe.h"
#include <stdexcept>

struct Scope { int* destroyed; ~Scope() { ++*destroyed; } };
extern "C" void lateThrow(int* destroyed) {
    Scope scope{destroyed};
    throw std::runtime_error("android10-late-exception");
}
__attribute__((destructor)) static void finish() { emit("late_module_fini=1\n"); }
