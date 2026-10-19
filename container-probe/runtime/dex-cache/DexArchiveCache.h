#ifndef A10VM_DEX_ARCHIVE_CACHE_H
#define A10VM_DEX_ARCHIVE_CACHE_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

#include "base/mem_map.h"

namespace art {

class DexArchiveCache {
 public:
    DexArchiveCache(int archive_fd, const char* entry, uint32_t crc, size_t size);
    MemMap Read(const std::string& location) const;
    void Publish(const uint8_t* bytes, size_t size) const;

 private:
    bool SourceUnchanged() const;
    int archive_fd_;
    size_t size_;
    std::array<uint64_t, 7> source_{};
    std::array<uint8_t, 32> key_{};
    std::string directory_;
    std::string path_;
};

}  // namespace art

#endif
