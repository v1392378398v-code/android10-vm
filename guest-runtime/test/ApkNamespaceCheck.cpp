#include <android/dlext.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

extern "C" void* __loader_shared_globals();
extern "C" android_namespace_t* __loader_android_create_namespace(const char*, const char*, const char*,
    uint64_t, const char*, android_namespace_t*, const void*);
extern "C" bool __loader_android_link_namespaces(android_namespace_t*, android_namespace_t*, const char*);

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    char directory[PATH_MAX];
    strlcpy(directory, argv[1], sizeof(directory));
    char* slash = strrchr(directory, '/');
    if (!slash) return 2;
    *slash = '\0';
    auto* ns = __loader_android_create_namespace("apk-code-path-check", directory, directory, 1,
        directory, nullptr, reinterpret_cast<const void*>(&main));
    if (!ns || !__loader_android_link_namespaces(ns, nullptr, "libc.so:libdl.so")) return 1;
    android_dlextinfo extension{};
    extension.flags = ANDROID_DLEXT_USE_NAMESPACE;
    extension.library_namespace = ns;
    void* handle = android_dlopen_ext(argv[1], RTLD_NOW | RTLD_LOCAL, &extension);
    auto shared = reinterpret_cast<void* (*)()>(handle ? dlsym(handle, "namespace_shared_globals") : nullptr);
    bool passed = shared && shared() == __loader_shared_globals();
    if (!handle) fprintf(stderr, "apk_namespace_error=%s\n", dlerror());
    if (handle) dlclose(handle);
    printf("apk_namespace_contents=%d\n", passed);
    return passed ? 0 : 1;
}
