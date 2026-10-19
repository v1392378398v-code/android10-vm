#include "Probe.h"
#include "ExceptionApi.h"
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <future>
#include <iomanip>
#include <memory>
#include <mutex>
#include <numeric>
#include <regex>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <vector>

static std::atomic<int> tls_destroyed{0};
struct ThreadState {
    int value = 29;
    ~ThreadState() { ++tls_destroyed; }
};
static thread_local ThreadState state;

bool cxxChecks() {
    std::vector<int> values{9, 2, 7, 1, 10};
    std::sort(values.begin(), values.end());
    bool passed = check(values == std::vector<int>({1, 2, 7, 9, 10}) &&
                        std::accumulate(values.begin(), values.end(), 0) == 29, "cxx_vector_algorithm");
    std::unordered_map<std::string, int> table;
    bool buckets = true;
    for (int round = 0; round < 64; ++round) {
        table.clear();
        table.rehash(97);
        for (int i = 0; i < 93; ++i) table.emplace("android10-key-" + std::to_string(i), i);
        for (int i = 0; i < 93; ++i) buckets &= table.at("android10-key-" + std::to_string(i)) == i;
        for (int i = 0; i < 93; i += 2) table.erase("android10-key-" + std::to_string(i));
        for (int i = 1; i < 93; i += 2) buckets &= table.at("android10-key-" + std::to_string(i)) == i;
    }
    table.clear();
    for (int i = 0; i < 128; ++i) table.emplace("android10-key-" + std::to_string(i), i);
    passed &= check(buckets && table.size() == 128 && table.at("android10-key-29") == 29,
                    "cxx_unordered_map_string");
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << "android10:" << 29 << ':' << std::fixed << std::setprecision(2) << 1.25;
    passed &= check(stream.str() == "android10:29:1.25", "cxx_iostream_locale");
    std::regex pattern("android([0-9]+):([0-9]+)");
    std::smatch match;
    std::string text = "android10:29";
    passed &= check(std::regex_match(text, match, pattern) && match[1] == "10" && match[2] == "29" &&
                    std::regex_replace(text, pattern, "$2/$1") == "29/10", "cxx_regex");
    int destroyed = 0;
    std::weak_ptr<int> weak;
    {
        auto shared = std::shared_ptr<int>(new int(29), [&](int* value) { delete value; ++destroyed; });
        weak = shared;
        auto second = weak.lock();
        passed &= check(second && *second == 29 && shared.use_count() == 2, "cxx_shared_ownership");
    }
    passed &= check(weak.expired() && destroyed == 1, "cxx_shared_destructor");
    std::unique_ptr<ModuleBase> base(moduleCreate());
    ModuleBase* object = base.get();
    passed &= check(dynamic_cast<ModuleDerived*>(object) != nullptr && object->value() == 29 &&
                    typeid(*object) == typeid(ModuleDerived), "cxx_cross_dso_rtti");
    bool bounds = false;
    try { values.at(128); } catch (const std::out_of_range&) { bounds = true; }
    passed &= check(bounds, "cxx_library_exception");
    std::once_flag once;
    int attempts = 0, successes = 0;
    auto initialize = [&] { if (++attempts == 1) throw std::runtime_error("retry"); ++successes; };
    try { std::call_once(once, initialize); } catch (const std::runtime_error&) { }
    std::call_once(once, initialize);
    std::call_once(once, initialize);
    passed &= check(attempts == 2 && successes == 1, "cxx_call_once_exception_retry");
    std::mutex mutex;
    std::condition_variable ready;
    int arrived = 0;
    bool start = false;
    std::atomic<int> sum{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < 4; ++i) threads.emplace_back([&] {
        std::unique_lock<std::mutex> lock(mutex);
        ++arrived;
        ready.notify_all();
        ready.wait(lock, [&] { return start; });
        lock.unlock();
        int module_destroyed = 0;
        try { moduleThrow(&module_destroyed); }
        catch (const ModuleError& error) {
            if (module_destroyed == 1 && error.code() == state.value) sum += state.value;
        }
    });
    {
        std::unique_lock<std::mutex> lock(mutex);
        ready.wait(lock, [&] { return arrived == 4; });
        start = true;
    }
    ready.notify_all();
    for (auto& thread : threads) thread.join();
    passed &= check(sum == 116 && tls_destroyed == 4, "cxx_threads_exception_tls_destructors");
    bool future_exception = false;
    auto future = std::async(std::launch::async, []() -> int { throw ModuleError(29); });
    try { future.get(); } catch (const ModuleError& error) { future_exception = error.code() == 29; }
    passed &= check(future_exception, "cxx_future_exception");
    emit("cxx_workers=4\ncxx_tls_destructors=%d\n", tls_destroyed.load());
    return passed;
}
