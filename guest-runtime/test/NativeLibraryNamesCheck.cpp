#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

struct Libraries { bool art = false, libc = false, linker = false, valid = true; };

static int inspect(dl_phdr_info* info, size_t, void* data) {
    auto* libraries = static_cast<Libraries*>(data);
    const char* name = strrchr(info->dlpi_name, '/');
    name = name ? name + 1 : info->dlpi_name;
    bool* found = !strcmp(name, "libart.so") ? &libraries->art :
            !strcmp(name, "libc.so") ? &libraries->libc :
            !strcmp(name, "linker64") ? &libraries->linker : nullptr;
    if (!found) return 0;
    *found = true;
    char magic[4]{};
    int file = open(info->dlpi_name, O_RDONLY | O_CLOEXEC);
    bool readable = file >= 0 && read(file, magic, sizeof(magic)) == sizeof(magic)
            && !memcmp(magic, ELFMAG, sizeof(magic));
    if (file >= 0) close(file);
    Dl_info address{};
    bool matches = dladdr(info->dlpi_phdr, &address) && address.dli_fname
            && !strcmp(address.dli_fname, info->dlpi_name);
    libraries->valid &= readable && matches;
    printf("library_name=%s readable=%d dladdr=%d\n", info->dlpi_name, readable, matches);
    return 0;
}

int main(int argc, char** argv) {
    void* art = dlopen("libart.so", RTLD_NOW);
    if (!art) { fprintf(stderr, "ART load: %s\n", dlerror()); return 1; }
    Libraries libraries;
    dl_iterate_phdr(inspect, &libraries);
    if (!libraries.art || !libraries.libc || !libraries.linker || !libraries.valid) return 1;
    if (argc > 1) {
        void* plugin = dlopen(argv[1], RTLD_NOW);
        auto openLibrary = plugin ? reinterpret_cast<void* (*)(const char*)>(dlsym(plugin, "npth_dlopen")) : nullptr;
        auto closeLibrary = plugin ? reinterpret_cast<void (*)(void*)>(dlsym(plugin, "npth_dlclose")) : nullptr;
        void* handle = openLibrary ? openLibrary("libart.so") : nullptr;
        if (!handle || !closeLibrary) { fprintf(stderr, "NPTH ART load: %s\n", dlerror()); return 1; }
        auto symbol = reinterpret_cast<void* (*)(void*, const char*)>(dlsym(plugin, "npth_dlsym_symtab"));
        if (!symbol || !symbol(handle, "_ZN3art7Runtime9instance_E")) {
            fprintf(stderr, "NPTH ART runtime symbol missing\n"); return 1;
        }
        const char* interstellarSymbols[] = {
            "_ZN3artL25DexFile_defineClassNativeEP7_JNIEnvP7_jclassP8_jstringP8_jobjectS7_S7_",
            "_ZN3artL29VMClassLoader_findLoadedClassEP7_JNIEnvP7_jclassP8_jobjectP8_jstring"};
        for (const char* name : interstellarSymbols) {
            if (!symbol(handle, name)) {
                fprintf(stderr, "Interstellar ART symbol missing: %s\n", name); return 1;
            }
        }
        puts("interstellar_art_symbols_complete=1");
        closeLibrary(handle);
        puts("npth_art_load_complete=1");
        dlclose(plugin);
    }
    dlclose(art);
    puts("native_library_names_complete=1");
    return 0;
}
