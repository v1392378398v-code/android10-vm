#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 3; }
    auto close = reinterpret_cast<void (*)(void*)>(dlsym(library, "_ZN7android8NuPlayer14closeAudioSinkEv"));
    if (!close) return 3;
    struct Player { void* padding; int* renderer; } player{};
    close(&player);
    int count = 0;
    player.renderer = &count;
    close(&player);
    dlclose(library);
    if (count != 1) return 4;
    puts("media_renderer_guard=1");
    return 0;
}
