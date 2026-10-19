#!/usr/bin/env python3
"""Select unchanged value marshalling, without generated HIDL service dependencies."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
runtime = root / "artifacts/container/runtime"
source = runtime / "upstream/system/libhidl/transport"
output = runtime / "hwbinder/hidl-values"
(output / "include/hidl").mkdir(parents=True, exist_ok=True)


def section(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("HIDL source markers changed")
    return text[text.index(start):text.index(end)]


header = (source / "include/hidl/HidlBinderSupport.h").read_text()
implementation = (source / "HidlBinderSupport.cpp").read_text()
declarations = section(header, "// ---------------------- hidl_handle",
                       "// ---------------------- MQDescriptor")
functions = section(implementation, "const size_t hidl_handle::kOffsetOfNativeHandle",
                    "sp<IBinder> getOrCreateCachedBinder")
(output / "include/hidl/HidlValueSupport.h").write_text(
    header[:header.index("#ifndef")] + "#pragma once\n"
    "#include <hidl/HidlSupport.h>\n#include <hwbinder/Parcel.h>\n"
    "namespace android { namespace hardware {\n" + declarations + "}}\n", encoding="utf-8")
(output / "HidlValues.cpp").write_text(
    implementation[:implementation.index("#define LOG_TAG")] +
    '#define LOG_TAG "HidlValues"\n#include <hidl/HidlValueSupport.h>\n'
    "#include <inttypes.h>\n#include <log/log.h>\n"
    "namespace android { namespace hardware {\n" + functions + "}}\n", encoding="utf-8")
