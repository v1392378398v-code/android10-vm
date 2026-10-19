#include "DexClassIndex.h"

#include <limits>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>
#include <vector>

namespace art {
namespace {

constexpr uint16_t kMissing = std::numeric_limits<uint16_t>::max();
struct Registry {
    std::shared_mutex mutex;
    std::unordered_map<const DexFile*, std::vector<uint16_t>> entries;
};

Registry& Indexes() {
    // ART can destroy DexFiles during shared-library shutdown.
    static Registry* registry = new Registry;
    return *registry;
}

const dex::ClassDef* Lookup(const DexFile& file, const std::vector<uint16_t>& index, dex::TypeIndex type) {
    uint16_t position = index[type.index_];
    return position == kMissing ? nullptr : &file.GetClassDef(position);
}

}  // namespace

const dex::ClassDef* FindIndexedClassDef(const DexFile& file, dex::TypeIndex type) {
    if (!type.IsValid() || type.index_ >= file.NumTypeIds()) return nullptr;
    Registry& registry = Indexes();
    {
        std::shared_lock<std::shared_mutex> lock(registry.mutex);
        auto found = registry.entries.find(&file);
        if (found != registry.entries.end()) return Lookup(file, found->second, type);
    }
    std::unique_lock<std::shared_mutex> lock(registry.mutex);
    auto inserted = registry.entries.emplace(&file, std::vector<uint16_t>());
    std::vector<uint16_t>& index = inserted.first->second;
    if (inserted.second) {
        index.assign(file.NumTypeIds(), kMissing);
        for (uint32_t i = 0; i < file.NumClassDefs(); ++i) {
            uint16_t type_index = file.GetClassDef(i).class_idx_.index_;
            if (type_index < index.size() && index[type_index] == kMissing)
                index[type_index] = static_cast<uint16_t>(i);
        }
    }
    return Lookup(file, index, type);
}

void ForgetClassIndex(const DexFile& file) {
    Registry& registry = Indexes();
    std::unique_lock<std::shared_mutex> lock(registry.mutex);
    registry.entries.erase(&file);
}

}  // namespace art
