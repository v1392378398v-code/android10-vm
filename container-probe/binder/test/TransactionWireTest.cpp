#include "TransactionLayout.h"
#include "ClientBuffers.h"
#include <array>
#include <cstdlib>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

using namespace a10binder;
static size_t checks = 0;
static void require(bool value, const char* name) {
    ++checks;
    if (!value) { fprintf(stderr, "FAIL: %s, errno=%d\n", name, errno); exit(1); }
}

struct Source {
    Packet body;
    std::vector<binder_size_t> offsets;
    size_t buffersSize = 0;
    template<class T> void object(const T& value) {
        offsets.push_back(body.data.size());
        body.append(value);
    }
    void buffer(const void* value, size_t length, int parent = -1, size_t offset = 0) {
        binder_buffer_object object{};
        object.hdr.type = BINDER_TYPE_PTR;
        object.buffer = reinterpret_cast<uintptr_t>(value);
        object.length = length;
        if (parent >= 0) {
            object.flags = BINDER_BUFFER_FLAG_HAS_PARENT;
            object.parent = parent; object.parent_offset = offset;
        }
        this->object(object);
        buffersSize += aligned(length);
    }
    bool encode(Packet* packet, size_t size = SIZE_MAX) {
        binder_transaction_data transaction{};
        transaction.data_size = body.data.size();
        transaction.offsets_size = offsets.size() * sizeof(binder_size_t);
        transaction.data.ptr.buffer = reinterpret_cast<uintptr_t>(body.data.data());
        transaction.data.ptr.offsets = reinterpret_cast<uintptr_t>(offsets.data());
        return serializeTransaction(BC_TRANSACTION, transaction, packet, size == SIZE_MAX ? buffersSize : size);
    }
};

static Packet clone(const Packet& source) {
    Packet result; result.header = source.header; result.data = source.data;
    for (int fd : source.fds) {
        int copied = fcntl(fd, F_DUPFD_CLOEXEC, 0);
        require(copied >= 0, "clone descriptor");
        result.fds.push_back(copied);
    }
    return result;
}
template<class T> static void put(Packet* packet, size_t at, const T& value) {
    require(at <= packet->data.size() && sizeof(T) <= packet->data.size() - at, "fixture bounds");
    memcpy(packet->data.data() + at, &value, sizeof(value));
}
static bool valid(const Packet& packet) {
    TransactionLayout layout;
    return validateTransaction(packet, &layout);
}
static int descriptors() {
    DIR* directory = opendir("/proc/self/fd");
    require(directory, "descriptor directory");
    int count = 0;
    while (dirent* entry = readdir(directory)) if (entry->d_name[0] != '.') ++count;
    closedir(directory);
    return count;
}
static bool readonly(uintptr_t address) {
    FILE* maps = fopen("/proc/self/maps", "r");
    require(maps, "maps directory");
    char line[512], mode[5];
    unsigned long begin, end;
    bool found = false;
    while (fgets(line, sizeof(line), maps)) {
        if (sscanf(line, "%lx-%lx %4s", &begin, &end, mode) == 3 && address >= begin && address < end) {
            found = mode[0] == 'r' && mode[1] == '-' && mode[2] == '-'; break;
        }
    }
    fclose(maps);
    return found;
}

int main() {
    char first[] = "alpha", second[] = "beta";
    const char* pair[]{first, second};
    Source source;
    source.buffer(pair, sizeof(pair));
    source.buffer(first, sizeof(first), 0, 0);
    source.buffer(second, sizeof(second), 0, sizeof(void*));
    Packet packet;
    require(source.encode(&packet) && valid(packet), "nested SG encoding");
    require(pair[0] == first && pair[1] == second, "sender pointers unchanged");
    TransactionLayout layout;
    require(validateTransaction(packet, &layout), "layout parse");
    {
        Packet copy = clone(packet);
        binder_transaction_data received;
        require(clientBuffers().receive(&copy, &received), "receive nested buffers");
        binder_buffer_object root;
        memcpy(&root, reinterpret_cast<const void*>(received.data.ptr.buffer), sizeof(root));
        const auto* local = reinterpret_cast<const char* const*>(root.buffer);
        require(local[0] != first && local[1] != second && strcmp(local[0], first) == 0 &&
                strcmp(local[1], second) == 0, "receiver pointers fixed up");
        require(readonly(received.data.ptr.buffer) && readonly(root.buffer), "read-only buffer mapping");
        clientBuffers().release(received.data.ptr.buffer);
    }
    auto malformed = [&](const char* name, auto mutation) {
        Packet copy = clone(packet);
        mutation(copy);
        require(!valid(copy), name);
    };
    size_t child = layout.objects[1].offset;
    malformed("self parent", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.parent = 1; put(&p, child, value);
    });
    malformed("out-of-bounds parent fixup", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.parent_offset = sizeof(pair); put(&p, child, value);
    });
    malformed("misaligned parent fixup", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.parent_offset = 1; put(&p, child, value);
    });
    malformed("overlapping fixups", [&](Packet& p) {
        auto value = layout.objects[2].buffer; value.parent_offset = 0; put(&p, layout.objects[2].offset, value);
    });
    malformed("unknown buffer flags", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.flags = 0x8000; put(&p, child, value);
    });
    malformed("pointer outside payload", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.buffer = UINT64_MAX; put(&p, child, value);
    });
    malformed("length overflow", [&](Packet& p) {
        auto value = layout.objects[1].buffer; value.length = UINT64_MAX; put(&p, child, value);
    });
    malformed("parent slot disagrees", [&](Packet& p) {
        put(&p, layout.objects[0].buffer.buffer, binder_uintptr_t(0));
    });
    malformed("truncated extra buffers", [&](Packet& p) { p.data.pop_back(); });
    malformed("unclaimed trailing bytes", [&](Packet& p) { p.data.push_back(0); });
    Packet rejected;
    require(!source.encode(&rejected, source.buffersSize - 8) && rejected.data.empty(), "short SG allocation");
    require(!source.encode(&rejected, source.buffersSize + 8) && rejected.data.empty(), "excess SG allocation");
    Source empty; empty.buffer(first, 0);
    Packet zero; require(empty.encode(&zero) && valid(zero), "non-null zero-length buffer");

    int pipeFds[2]; require(pipe2(pipeFds, O_CLOEXEC) == 0, "pipe fixture");
    std::array<int, 3> handle{pipeFds[0], pipeFds[1], 42};
    Source fds; fds.buffer(handle.data(), sizeof(handle));
    binder_fd_array_object array{}; array.hdr.type = BINDER_TYPE_FDA; array.num_fds = 2;
    fds.object(array);
    Packet handles; require(fds.encode(&handles) && valid(handles), "FD array encoding");
    require(handle[0] == pipeFds[0] && handle[1] == pipeFds[1], "sender FDs unchanged");
    require(validateTransaction(handles, &layout), "FD array layout");
    {
        Packet copy = clone(handles);
        put(&copy, layout.objects[0].buffer.buffer, uint32_t(1));
        require(!valid(copy), "duplicate descriptor slot");
    }
    {
        Packet copy = clone(handles);
        auto invalid = array; invalid.num_fds = kMaxFds + 1;
        put(&copy, layout.objects[1].offset, invalid);
        require(!valid(copy), "FD count overflow");
    }
    {
        Packet copy = clone(handles);
        int saved0 = copy.fds[0], saved1 = copy.fds[1];
        binder_transaction_data received;
        require(clientBuffers().receive(&copy, &received), "receive FD array");
        binder_buffer_object root;
        memcpy(&root, reinterpret_cast<void*>(received.data.ptr.buffer), sizeof(root));
        const int* values = reinterpret_cast<int*>(root.buffer);
        require(values[0] == saved0 && values[1] == saved1 && values[2] == 42, "FD array fixup");
        require((fcntl(saved0, F_GETFD) & FD_CLOEXEC) && (fcntl(saved1, F_GETFD) & FD_CLOEXEC), "CLOEXEC retained");
        clientBuffers().release(received.data.ptr.buffer);
        require(fcntl(saved0, F_GETFD) == -1 && errno == EBADF &&
                fcntl(saved1, F_GETFD) == -1 && errno == EBADF, "array descriptors freed");
    }
    int before = descriptors();
    handle[1] = -1;
    for (int n = 0; n < 16; ++n) require(!fds.encode(&rejected) && rejected.data.empty(), "failed FD copy rollback");
    require(descriptors() == before, "failed descriptor copy does not leak");
    close(pipeFds[0]); close(pipeFds[1]);
    a10binder_buffer_stats stats{}; clientBuffers().stats(&stats);
    require(stats.active == 0 && stats.bytes == 0 && stats.allocated == stats.freed, "all buffers reclaimed");
    printf("PASS: %zu transport assertions (SG layout, fixups, FD ownership, malformed input)\n", checks);
}
