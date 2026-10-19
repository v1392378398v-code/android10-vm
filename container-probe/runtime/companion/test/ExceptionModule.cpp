#include "ExceptionApi.h"

ModuleError::ModuleError(int code) : std::runtime_error("android10-module-error"), code_(code) { }
ModuleError::~ModuleError() = default;
ModuleBase::~ModuleBase() = default;
ModuleDerived::~ModuleDerived() = default;
int ModuleDerived::value() const { return 29; }

struct Scope {
    int* destroyed;
    ~Scope() { ++*destroyed; }
};

extern "C" void moduleThrow(int* destroyed) {
    Scope scope{destroyed};
    throw ModuleError(29);
}

extern "C" void moduleInvoke(void (*callback)(void*), void* context, int* destroyed) {
    Scope scope{destroyed};
    callback(context);
}

extern "C" ModuleBase* moduleCreate() { return new ModuleDerived; }
