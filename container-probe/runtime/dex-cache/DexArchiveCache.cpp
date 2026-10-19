#include "DexArchiveCache.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "android-base/unique_fd.h"

// The guest ships Android 10 BoringSSL; this one-shot API has no opaque ABI state.
extern "C" uint8_t* SHA256(const uint8_t* data, size_t size, uint8_t* digest);

namespace art {
namespace {

constexpr std::array<uint8_t, 8> kMagic{{'A', '1', '0', 'D', 'E', 'X', '0', '1'}};
struct Header {
    std::array<uint8_t, 8> magic;
    uint64_t size;
    std::array<uint8_t, 32> key;
    std::array<uint8_t, 32> digest;
};
static_assert(sizeof(Header) == 80, "Persistent DEX header layout changed");

bool SourceIdentity(int fd, std::array<uint64_t, 7>* identity) {
    struct stat status{};
    if (fstat(fd, &status) != 0 || !S_ISREG(status.st_mode)) return false;
    *identity = {{static_cast<uint64_t>(status.st_dev), static_cast<uint64_t>(status.st_ino),
        static_cast<uint64_t>(status.st_size), static_cast<uint64_t>(status.st_mtim.tv_sec),
        static_cast<uint64_t>(status.st_mtim.tv_nsec), static_cast<uint64_t>(status.st_ctim.tv_sec),
        static_cast<uint64_t>(status.st_ctim.tv_nsec)}};
    return true;
}

bool WriteAll(int fd, const void* data, size_t size) {
    const auto* bytes = static_cast<const uint8_t*>(data);
    while (size > 0) {
        ssize_t written = write(fd, bytes, size);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) return false;
        bytes += written;
        size -= written;
    }
    return true;
}

}  // namespace

DexArchiveCache::DexArchiveCache(int archive_fd, const char* entry, uint32_t crc, size_t size)
    : archive_fd_(archive_fd), size_(size) {
    const char* directory = getenv("A10VM_DEX_CACHE");
    if (directory == nullptr || directory[0] != '/' || !SourceIdentity(archive_fd, &source_)) return;
    directory_ = directory;
    std::string identity(reinterpret_cast<const char*>(source_.data()), sizeof(source_));
    const uint64_t metadata[] = {crc, size};
    identity.append(reinterpret_cast<const char*>(metadata), sizeof(metadata));
    identity.append(entry);
    SHA256(reinterpret_cast<const uint8_t*>(identity.data()), identity.size(), key_.data());
    const char* hex = "0123456789abcdef";
    path_ = directory_ + "/";
    for (uint8_t byte : key_) {
        path_ += hex[byte >> 4];
        path_ += hex[byte & 15];
    }
    path_ += ".adex";
}

bool DexArchiveCache::SourceUnchanged() const {
    std::array<uint64_t, 7> current;
    return SourceIdentity(archive_fd_, &current) && current == source_;
}

MemMap DexArchiveCache::Read(const std::string& location) const {
    if (path_.empty()) return MemMap();
    android::base::unique_fd fd(open(path_.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    if (fd.get() < 0) return MemMap();
    struct stat status{};
    Header header{};
    if (fstat(fd.get(), &status) != 0 || !S_ISREG(status.st_mode) ||
            status.st_size != static_cast<off_t>(sizeof(header) + size_) ||
            TEMP_FAILURE_RETRY(pread(fd.get(), &header, sizeof(header), 0)) != sizeof(header) ||
            header.magic != kMagic || header.size != size_ || header.key != key_) return MemMap();
    std::string error;
    MemMap map = MemMap::MapFile(size_, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd.get(),
        sizeof(header), false, location.c_str(), &error);
    if (!map.IsValid()) return MemMap();
    std::array<uint8_t, 32> digest;
    SHA256(map.Begin(), map.Size(), digest.data());
    if (digest != header.digest || !SourceUnchanged()) return MemMap();
    return map;
}

void DexArchiveCache::Publish(const uint8_t* bytes, size_t size) const {
    if (path_.empty() || size != size_ || !SourceUnchanged()) return;
    const std::string parent = directory_.substr(0, directory_.find_last_of('/'));
    if (mkdir(parent.c_str(), 0700) != 0 && errno != EEXIST) return;
    if (mkdir(directory_.c_str(), 0700) != 0 && errno != EEXIST) return;
    Header header{kMagic, size, key_, {}};
    SHA256(bytes, size, header.digest.data());
    std::string temporary = path_ + ".tmp-XXXXXX";
    android::base::unique_fd fd(mkstemp(&temporary[0]));
    if (fd.get() < 0) return;
    fcntl(fd.get(), F_SETFD, FD_CLOEXEC);
    // Rename publishes complete bytes; interrupted/failed writes never become cache hits.
    if (WriteAll(fd.get(), &header, sizeof(header)) && WriteAll(fd.get(), bytes, size) &&
            SourceUnchanged()) rename(temporary.c_str(), path_.c_str());
    unlink(temporary.c_str());
}

}  // namespace art
