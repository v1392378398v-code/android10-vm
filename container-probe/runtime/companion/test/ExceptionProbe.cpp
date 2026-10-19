#include "Probe.h"
#include "ExceptionApi.h"
#include <exception>

struct Scope {
    int* destroyed;
    ~Scope() { ++*destroyed; }
};

static void callback(void* context) {
    Scope scope{static_cast<int*>(context)};
    throw std::logic_error("android10-callback");
}

struct RetryInitialization {
    static int attempts;
    RetryInitialization() { if (++attempts == 1) throw ModuleError(29); }
};
int RetryInitialization::attempts;
static RetryInitialization& guarded() { static RetryInitialization value; return value; }

bool exceptionChecks() {
    int module_destroyed = 0, program_destroyed = 0;
    bool caught = false;
    std::exception_ptr saved;
    try {
        Scope scope{&program_destroyed};
        moduleThrow(&module_destroyed);
    } catch (const ModuleError& error) {
        caught = error.code() == 29 && !strcmp(error.what(), "android10-module-error");
        saved = std::current_exception();
    }
    bool passed = check(caught && module_destroyed == 1 && program_destroyed == 1,
                        "exception_cross_dso_raii");
    caught = false;
    try { std::rethrow_exception(saved); }
    catch (const ModuleError& error) { caught = error.code() == 29; }
    passed &= check(caught, "exception_ptr_rethrow");
    module_destroyed = program_destroyed = 0;
    caught = false;
    try { moduleInvoke(callback, &program_destroyed, &module_destroyed); }
    catch (const std::logic_error& error) { caught = !strcmp(error.what(), "android10-callback"); }
    passed &= check(caught && module_destroyed == 1 && program_destroyed == 1,
                    "exception_callback_cross_dso");
    bool nested = false;
    try {
        try { throw ModuleError(29); }
        catch (...) { std::throw_with_nested(std::runtime_error("outer")); }
    } catch (const std::runtime_error& outer) {
        try { std::rethrow_if_nested(outer); }
        catch (const ModuleError& inner) { nested = inner.code() == 29; }
    }
    passed &= check(nested, "exception_nested");
    caught = false;
    try { guarded(); } catch (const ModuleError&) { caught = true; }
    guarded();
    guarded();
    passed &= check(caught && RetryInitialization::attempts == 2, "exception_static_guard_retry");
    return passed;
}
