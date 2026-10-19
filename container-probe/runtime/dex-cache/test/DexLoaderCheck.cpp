#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <string>
#include <vector>
#include <zlib.h>

#include "android-base/logging.h"
#include "base/mem_map.h"
#include "dex/art_dex_file_loader.h"
#include "dex/dex_file.h"

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    android::base::InitLogging(argv);
    art::MemMap::Init();
    const bool verify = argc < 3 || strcmp(argv[2], "--skip-verify") != 0;
    const std::string location = argc > 3 ? argv[3] : argv[1];
    art::ArtDexFileLoader loader;
    std::vector<std::unique_ptr<const art::DexFile>> files;
    std::string error;
    const int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (fd < 0 || !loader.Open(fd, location, verify, verify, &error, &files)) {
        fprintf(stderr, "dex_load_error=%s\n", error.c_str());
        return 1;
    }
    printf("dex_count=%zu\n", files.size());
    for (const auto& file : files) {
        printf("dex_bytes=%zu:%lu location=%s checksum=%u readonly=%d\n", file->Size(),
               crc32(0, file->Begin(), file->Size()), file->GetLocation().c_str(),
               file->GetLocationChecksum(), file->IsReadOnly());
    }
    FILE* maps = fopen("/proc/self/maps", "r");
    if (!maps) return 3;
    char line[4096];
    unsigned cached = 0;
    while (fgets(line, sizeof(line), maps)) {
        if (strstr(line, ".adex")) ++cached;
    }
    fclose(maps);
    printf("dex_cache_mappings=%u\n", cached);
    return 0;
}
