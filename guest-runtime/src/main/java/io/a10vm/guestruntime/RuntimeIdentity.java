package io.a10vm.guestruntime;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;

final class RuntimeIdentity {
    private static final class Evidence {
        final Map<String, String> values = new HashMap<>();
        final Set<String> mappings = new HashSet<>();
    }

    private static Evidence parse(String output, String prefix) {
        Evidence evidence = new Evidence();
        String marker = prefix.toUpperCase(java.util.Locale.ROOT) + "_MAP\t";
        for (String line : output.split("\n")) {
            if (line.startsWith(marker)) evidence.mappings.add(line.substring(marker.length()));
            else if (line.startsWith(prefix + "_") && line.contains("=")) {
                String[] item = line.split("=", 2);
                if (evidence.values.put(item[0], item[1]) != null)
                    throw new IllegalStateException("Duplicate process identity field");
            }
        }
        return evidence;
    }

    private static String mappingName(String path) {
        String value = path.trim();
        if (value.endsWith(" (deleted)")) value = value.substring(0, value.length() - " (deleted)".length());
        return value;
    }

    private static boolean isJitMapping(String mapping) {
        switch (mapping) {
            case "/memfd:jit-cache":
            case "/memfd:/jit-cache":
            case "/memfd:/ jit-cache":
            case "/memfd:jit-code-cache":
            case "/memfd:/jit-code-cache":
            case "/memfd:/ jit-code-cache":
            case "[anon:dalvik-jit-code-cache]":
            case "/dev/ashmem/dalvik-jit-code-cache":
                return true;
            default:
                return false;
        }
    }

    private static void verifyBase(Evidence evidence, String prefix, RuntimeFiles files, String... required) throws Exception {
        String uid = Integer.toString(android.os.Process.myUid());
        Map<String, String> values = evidence.values;
        if (!uid.equals(values.get(prefix + "_uid")) || !uid.equals(values.get(prefix + "_euid")) ||
                !"0000000000000000".equals(values.get(prefix + "_cap_eff")) ||
                !values.getOrDefault(prefix + "_selinux", "").matches("u:r:untrusted_app(?:_[0-9]+)?:s0(?::.*)?"))
            throw new IllegalStateException("Guest process identity mismatch");
        Set<String> allowed = new HashSet<>();
        JSONArray inputs = files.inputs().getJSONArray("files");
        for (int i = 0; i < inputs.length(); ++i)
            allowed.add(files.nativeFile(inputs.getJSONObject(i).getString("logical")).getCanonicalPath());
        Map<String, String> expected = new HashMap<>();
        for (String name : required) expected.put(name, files.nativeFile(name).getCanonicalPath());
        verifyMappings(evidence.mappings, allowed, expected, new File(files.directory, "rootfs"));
    }

    static void verifyMappings(Iterable<String> mappings, Set<String> allowed,
            Map<String, String> required) throws Exception {
        verifyMappings(mappings, allowed, required, null);
    }

    static void verifyMappings(Iterable<String> mappings, Set<String> allowed,
            Map<String, String> required, File rootfs) throws Exception {
        Set<String> observed = new HashSet<>();
        for (String mapping : mappings) {
            String name = mappingName(mapping);
            // ART JIT caches are anonymous executable memory, not packaged ELF files.
            if (!isJitMapping(name)) {
                String physical = new File(name).getCanonicalPath();
                if (rootfs != null && !allowed.contains(physical))
                    physical = GuestMappingPaths.resolve(rootfs, name, allowed);
                observed.add(physical);
            }
        }
        Set<String> unexpected = new HashSet<>(observed);
        unexpected.removeAll(allowed);
        if (!unexpected.isEmpty())
            throw new IllegalStateException("Unexpected guest executable mapping: " + unexpected);
        for (Map.Entry<String, String> item : required.entrySet()) {
            String name = item.getKey(), expected = item.getValue();
            if (!observed.contains(expected)) {
                Set<String> missing = new HashSet<>(allowed);
                missing.removeAll(observed);
                throw new IllegalStateException("Missing guest executable mapping: " + name +
                        " expected=" + expected + " observed=" + observed + " missing=" + missing);
            }
        }
    }

    static void verifyArt(String output, String nonce, RuntimeFiles files, File roundTrip) throws Exception {
        Evidence evidence = parse(output, "art");
        Map<String, String> values = evidence.values;
        verifyBase(evidence, "art", files, "libart.so", "libc.so", "dalvikvm64", "libjavacore.so", "ld-android.so");
        if (!nonce.equals(values.get("art_nonce")) ||
                !"1".equals(values.get("art_thread")) || !"1".equals(values.get("art_file_roundtrip")) ||
                !"1".equals(values.get("art_directory_roundtrip")) ||
                !"1".equals(values.get("art_runtime_ready")))
            throw new IllegalStateException("ART identity or execution checks failed");
        if (!nonce.equals(new String(Files.readAllBytes(roundTrip.toPath()), StandardCharsets.UTF_8)))
            throw new IllegalStateException("ART private file round trip mismatch");
    }

    static void verifyFramework(String output, String nonce, RuntimeFiles files) throws Exception {
        Evidence evidence = parse(output, "framework");
        verifyBase(evidence, "framework", files, "libart.so", "libc.so", "app_process64",
                "libandroid_runtime.so", "libbinder.so", "ld-android.so", "liba10vm-binder-devices.so");
        Map<String, String> values = evidence.values;
        if (!"29".equals(values.get("framework_sdk")) || !nonce.equals(values.get("framework_nonce")) ||
                !values.getOrDefault("framework_server_pid", "0").matches("[1-9][0-9]*") ||
                !values.getOrDefault("framework_client_pid", "0").matches("[1-9][0-9]*") ||
                !"64".equals(values.get("framework_transactions")) || !"1".equals(values.get("framework_complete")))
            throw new IllegalStateException("Android framework RPC checks failed");
    }

    static void verifyProcess(int pid, RuntimeFiles files) throws Exception {
        String base = "/proc/" + pid;
        StringBuilder output = new StringBuilder();
        for (String line : Files.readAllLines(new File(base, "status").toPath(), StandardCharsets.UTF_8)) {
            if (line.startsWith("Uid:")) {
                String[] ids = line.substring(4).trim().split("\\s+");
                String uid = Integer.toString(android.os.Process.myUid());
                if (ids.length != 4 || !java.util.Arrays.stream(ids).allMatch(uid::equals))
                    throw new IllegalStateException("Child UID mismatch");
                output.append("process_uid=").append(ids[0]).append("\nprocess_euid=").append(ids[1]).append('\n');
            }
            if (line.startsWith("CapEff:")) output.append("process_cap_eff=").append(line.substring(7).trim()).append('\n');
        }
        output.append("process_selinux=").append(new String(Files.readAllBytes(new File(base, "attr/current").toPath()),
                StandardCharsets.UTF_8).trim()).append('\n');
        for (String line : Files.readAllLines(new File(base, "maps").toPath(), StandardCharsets.UTF_8)) {
            String[] fields = line.split("\\s+", 6);
            if (fields.length == 6 && fields[1].contains("x") && fields[5].startsWith("/"))
                output.append("PROCESS_MAP\t").append(fields[5]).append('\n');
        }
        verifyBase(parse(output.toString(), "process"), "process", files, "libc.so", "ld-android.so");
    }
}
