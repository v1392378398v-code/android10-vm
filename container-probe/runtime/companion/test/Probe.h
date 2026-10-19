#pragma once
#include "../../test/ProbeOutput.h"

bool mathChecks();
extern "C" bool complexChecks();
bool cxxChecks();
bool exceptionChecks();
bool unwindChecks();
bool lateExceptionChecks(const char* module);
