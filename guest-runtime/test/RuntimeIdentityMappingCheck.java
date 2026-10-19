package io.a10vm.guestruntime;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public final class RuntimeIdentityMappingCheck {
    private static final String LIBC = "/data/app/io.a10vm/lib/arm64/liba10vm-libc.so";
    private static final String LINKER = "/data/app/io.a10vm/lib/arm64/liba10vm-ld-android.so";
    private static final Set<String> ALLOWED = new HashSet<>(Arrays.asList(LIBC, LINKER));
    private static final Map<String, String> REQUIRED = new HashMap<>();

    static {
        REQUIRED.put("libc.so", LIBC);
        REQUIRED.put("ld-android.so", LINKER);
    }

    private static List<String> with(String mapping) {
        return new ArrayList<>(Arrays.asList(LIBC, LINKER, mapping));
    }

    private static void rejected(List<String> mappings, String message) throws Exception {
        try {
            RuntimeIdentity.verifyMappings(mappings, ALLOWED, REQUIRED);
        } catch (IllegalStateException expected) {
            if (!expected.getMessage().startsWith(message)) throw expected;
            return;
        }
        throw new AssertionError("Executable mappings unexpectedly accepted: " + mappings);
    }

    public static void main(String[] args) throws Exception {
        RuntimeIdentity.verifyMappings(Arrays.asList(LIBC, LINKER), ALLOWED, REQUIRED);
        RuntimeIdentity.verifyMappings(Arrays.asList(LIBC + " (deleted)", LINKER), ALLOWED, REQUIRED);
        String[] caches = {
            "/memfd:jit-cache", "/memfd:/jit-cache",
            "/memfd:/ jit-cache",
            "/memfd:jit-code-cache", "/memfd:/jit-code-cache",
            "/memfd:/ jit-code-cache",
            "[anon:dalvik-jit-code-cache]", "/dev/ashmem/dalvik-jit-code-cache"
        };
        for (String cache : caches) {
            RuntimeIdentity.verifyMappings(with(cache), ALLOWED, REQUIRED);
            RuntimeIdentity.verifyMappings(with("  " + cache + " (deleted)  "), ALLOWED, REQUIRED);
        }
        for (String mapping : new String[] {
                "/system/lib64/libc.so", "/data/local/tmp/jit-cache", "/data/local/tmp/libforeign.so",
                "/memfd:other", "/memfd:jit-cache-extra", "/memfd:/jit-cache/libforeign.so",
                "/memfd:/ jit-cache-extra", "/memfd:/ jit-cache/libforeign.so",
                "/memfd:jit-cache (deleted) extra", "/dev/ashmem/dalvik-jit-code-cache-extra",
                "[anon:dalvik-jit-code-cache-extra]", "/memfd:jit-data-cache"}) {
            rejected(with(mapping), "Unexpected guest executable mapping:");
        }
        rejected(Arrays.asList(LINKER, caches[1]), "Missing guest executable mapping: libc.so");
        rejected(Arrays.asList(LIBC, caches[1]), "Missing guest executable mapping: ld-android.so");
        rejected(Arrays.asList(caches), "Missing guest executable mapping:");
        RuntimeIdentity.verifyMappings(Arrays.asList(new File(LIBC).getParent() +
                "/../arm64/" + new File(LIBC).getName(), LINKER), ALLOWED, REQUIRED);
        Path temporary = Files.createTempDirectory("guest-mapping-paths-");
        Path rootfs = temporary.resolve("rootfs");
        Path nativeLibc = temporary.resolve("libc.so");
        Files.write(nativeLibc, new byte[] {1});
        Files.createDirectories(rootfs.resolve("system/lib64"));
        Files.createDirectories(rootfs.resolve("apex"));
        Files.createSymbolicLink(rootfs.resolve("system/lib64/libc.so"), nativeLibc);
        Files.createSymbolicLink(rootfs.resolve("apex/runtime"), Paths.get("/system"));
        Map<String, String> guestRequired = new HashMap<>();
        guestRequired.put("libc.so", nativeLibc.toFile().getCanonicalPath());
        Set<String> guestAllowed = new HashSet<>(guestRequired.values());
        RuntimeIdentity.verifyMappings(Arrays.asList("/apex/runtime/lib64/libc.so"),
                guestAllowed, guestRequired, rootfs.toFile());
        try {
            RuntimeIdentity.verifyMappings(Arrays.asList("/apex/runtime/lib64/foreign.so"),
                    guestAllowed, guestRequired, rootfs.toFile());
            throw new AssertionError("Guest foreign mapping unexpectedly accepted");
        } catch (IllegalStateException expected) {
            if (!expected.getMessage().startsWith("Unexpected guest executable mapping:")) throw expected;
        }
        try (java.util.stream.Stream<Path> paths = Files.walk(temporary)) {
            paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                try { Files.delete(path); }
                catch (java.io.IOException error) { throw new java.io.UncheckedIOException(error); }
            });
        }
        System.out.println("runtime_identity_guest_aliases_complete=1");
        System.out.println("runtime_identity_jit_mappings_complete=1");
        System.out.println("runtime_identity_external_mappings_rejected=1");
        System.out.println("runtime_identity_required_mappings_checked=1");
    }
}
