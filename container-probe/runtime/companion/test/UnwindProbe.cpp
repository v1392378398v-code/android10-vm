#include "Probe.h"
#include <dlfcn.h>
#include <unwind.h>

struct Frames { int count = 0; int named = 0; };
static _Unwind_Reason_Code record(_Unwind_Context* context, void* opaque) {
    auto* frames = static_cast<Frames*>(opaque);
    uintptr_t ip = _Unwind_GetIP(context);
    if (!ip) return _URC_END_OF_STACK;
    Dl_info info{};
    ++frames->count;
    if (dladdr(reinterpret_cast<void*>(ip), &info) && info.dli_fname) ++frames->named;
    return frames->count < 32 ? _URC_NO_REASON : _URC_END_OF_STACK;
}

__attribute__((noinline)) static void third(Frames* frames) { _Unwind_Backtrace(record, frames); }
__attribute__((noinline)) static void second(Frames* frames) { third(frames); }
__attribute__((noinline)) static void first(Frames* frames) { second(frames); }

bool unwindChecks() {
    Frames frames;
    first(&frames);
    emit("unwind_frames=%d\nunwind_named_frames=%d\n", frames.count, frames.named);
    Dl_info info{};
    bool found = dladdr(reinterpret_cast<void*>(&_Unwind_Backtrace), &info);
    emit("source_unwind=%s\n", found ? info.dli_fname : "");
    return check(frames.count >= 5 && frames.named == frames.count, "unwind_backtrace_frames") &&
           check(found, "unwind_library_identity");
}
