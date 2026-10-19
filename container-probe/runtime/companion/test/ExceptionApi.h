#pragma once
#include <stdexcept>

class ModuleError final : public std::runtime_error {
public:
    explicit ModuleError(int code);
    ~ModuleError() override;
    int code() const { return code_; }
private:
    int code_;
};

class ModuleBase {
public:
    virtual ~ModuleBase();
    virtual int value() const = 0;
};

class ModuleDerived final : public ModuleBase {
public:
    ~ModuleDerived() override;
    int value() const override;
};

extern "C" void moduleThrow(int* destroyed);
extern "C" void moduleInvoke(void (*callback)(void*), void* context, int* destroyed);
extern "C" ModuleBase* moduleCreate();
