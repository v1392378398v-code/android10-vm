#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <fcntl.h>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "android-base/logging.h"
#include "base/mem_map.h"
#include "dex/art_dex_file_loader.h"
#include "dex/dex_file.h"

static const art::dex::ClassDef* Linear(const art::DexFile& file, art::dex::TypeIndex type) {
    for (uint32_t i = 0; i < file.NumClassDefs(); ++i)
        if (file.GetClassDef(i).class_idx_ == type) return &file.GetClassDef(i);
    return nullptr;
}

static bool Check(const art::DexFile& file) {
    for (uint32_t i = 0; i < file.NumTypeIds(); ++i) {
        art::dex::TypeIndex type(i);
        if (file.FindClassDef(type) != Linear(file, type)) return false;
    }
    return file.FindClassDef(art::dex::TypeIndex(0xffff)) == nullptr;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    android::base::InitLogging(argv);
    art::MemMap::Init();
    art::ArtDexFileLoader loader;
    std::vector<std::unique_ptr<const art::DexFile>> files;
    std::string error;
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (fd < 0 || !loader.Open(fd, argv[1], false, false, &error, &files)) {
        fprintf(stderr, "lookup_load_error=%s\n", error.c_str());
        return 1;
    }
    for (const auto& file : files) {
        if (!Check(*file)) return 3;
        std::vector<const art::dex::ClassDef*> expected(file->NumTypeIds(), nullptr);
        for (uint32_t i = 0; i < file->NumTypeIds(); ++i)
            expected[i] = Linear(*file, art::dex::TypeIndex(i));
        std::atomic<bool> correct{true};
        std::vector<std::thread> readers;
        for (unsigned worker = 0; worker < 4; ++worker) readers.emplace_back([&] {
            for (unsigned iteration = 0; iteration < 16; ++iteration)
                for (uint32_t i = 0; i < expected.size(); ++i)
                    if (file->FindClassDef(art::dex::TypeIndex(i)) != expected[i]) correct = false;
        });
        for (auto& reader : readers) reader.join();
        if (!correct) return 4;
        if (file->NumClassDefs() >= 2) {
            if (!file->EnableWrite()) return 5;
            auto& first = const_cast<art::dex::ClassDef&>(file->GetClassDef(0));
            auto& last = const_cast<art::dex::ClassDef&>(file->GetClassDef(file->NumClassDefs() - 1));
            std::swap(first.class_idx_.index_, last.class_idx_.index_);
            if (!Check(*file) || !file->DisableWrite() || !Check(*file)) return 6;
        }
        constexpr unsigned lookups = 200000;
        const art::dex::ClassDef* volatile sink = nullptr;
        auto measure = [&](bool indexed) {
            auto start = std::chrono::steady_clock::now();
            for (unsigned i = 0; i < lookups; ++i) {
                art::dex::TypeIndex type((i * 7919u) % file->NumTypeIds());
                sink = indexed ? file->FindClassDef(type) : Linear(*file, type);
            }
            return std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now() - start).count() / lookups;
        };
        auto linear = measure(false), indexed = measure(true);
        printf("lookup_class_defs=%u lookup_types=%u linear_ns=%lld indexed_ns=%lld\n",
               file->NumClassDefs(), file->NumTypeIds(),
               static_cast<long long>(linear), static_cast<long long>(indexed));
        if (file->NumClassDefs() >= 4096 && indexed * 2 >= linear) return 7;
        (void)sink;
    }
    printf("lookup_correctness_concurrency_mutation=1\n");
    return 0;
}
