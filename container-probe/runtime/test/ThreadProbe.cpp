#include "ProbeOutput.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>

static __thread int thread_value = 29;
static pthread_key_t key;
#ifndef A10VM_DYNAMIC_PROBE
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
#endif
static int key_destructors;
static int cpp_destructors;
static pid_t worker_tid;
static int* worker_errno;
static int* worker_tls;

struct ThreadObject {
    int value = 29;
    ~ThreadObject() { if (value == 30) ++cpp_destructors; }
};

static void destroyKey(void* value) {
    if (value == &thread_value && thread_value == 30) ++key_destructors;
}

static void* worker(void*) {
#ifndef A10VM_DYNAMIC_PROBE
    pthread_mutex_lock(&gate);
    pthread_mutex_unlock(&gate);
#endif
    static thread_local ThreadObject object;
    bool passed = thread_value == 29 && object.value == 29 &&
                  pthread_getspecific(key) == nullptr;
    worker_tid = gettid();
    worker_errno = &errno;
    worker_tls = &thread_value;
    thread_value = 30;
    object.value = 30;
    errno = 0;
    passed &= open("/a10vm-does-not-exist", O_RDONLY) == -1 && errno == ENOENT;
    passed &= pthread_setspecific(key, &thread_value) == 0 &&
              pthread_getspecific(key) == &thread_value;
    return reinterpret_cast<void*>(static_cast<uintptr_t>(passed));
}

bool threadChecks() {
    if (!check(pthread_key_create(&key, destroyKey) == 0, "bootstrap_key_create")) return false;
    bool passed = true;
    thread_value = 31;
    errno = EDOM;
    int* main_errno = &errno;
    for (int i = 0; i < 2; ++i) {
#ifndef A10VM_DYNAMIC_PROBE
        // Serialize allocator use: this slice uses the upstream linker allocator.
        pthread_mutex_lock(&gate);
#endif
        pthread_t thread;
        int created = pthread_create(&thread, nullptr, worker, nullptr);
#ifndef A10VM_DYNAMIC_PROBE
        pthread_mutex_unlock(&gate);
#endif
        if (!check(created == 0, "bootstrap_thread_create")) { passed = false; break; }
        void* result = nullptr;
        passed &= check(pthread_join(thread, &result) == 0 && result == reinterpret_cast<void*>(1),
                        "bootstrap_thread_join");
        passed &= check(worker_tid != gettid() && worker_errno != main_errno &&
                        worker_tls != &thread_value && thread_value == 31 && errno == EDOM &&
                        pthread_getspecific(key) == nullptr, "bootstrap_tls_errno_isolation");
        passed &= check(key_destructors == i + 1 && cpp_destructors == i + 1,
                        "bootstrap_thread_destructors");
    }
    passed &= check(pthread_key_delete(key) == 0, "bootstrap_key_delete");
    emit("thread_rounds=%d\nkey_destructors=%d\ncpp_destructors=%d\n",
         key_destructors, key_destructors, cpp_destructors);
    return passed;
}
