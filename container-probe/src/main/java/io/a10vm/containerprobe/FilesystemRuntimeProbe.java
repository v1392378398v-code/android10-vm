package io.a10vm.containerprobe;

import android.system.Os;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Guest paths and exec through the source runtime in the ordinary application UID. */
final class FilesystemRuntimeProbe {
    private final LoaderProbe runtime;

    FilesystemRuntimeProbe(LoaderProbe runtime) { this.runtime = runtime; }

    JSONObject run(File logs, File seed, String nonce) throws Exception {
        JSONObject inputs = runtime.readInputs("filesystem-inputs.json");
        Set<String> allowed = runtime.verifyInputs(inputs.getJSONArray("files"));
        String program = runtime.nativeFile("liba10vm-p2-filesystem.so").getCanonicalPath();
        String linker = runtime.nativeFile("liba10vm-source-linker.so").getCanonicalPath();
        File root = new File(seed, "filesystem-rootfs");
        for (String path : Arrays.asList("system/etc", "system/bin", "system/runtime", "data/local/tmp", "apex")) {
            Files.createDirectories(new File(root, path).toPath());
        }
        for (String path : Arrays.asList("system/etc/a10vm-marker", "system/runtime/a10vm-marker")) {
            Files.write(new File(root, path).toPath(), nonce.getBytes(StandardCharsets.UTF_8));
        }
        Map<String, String> links = new HashMap<>();
        links.put("system/etc/absolute-marker", "/system/etc/a10vm-marker");
        links.put("system/etc/relative-marker", "a10vm-marker");
        links.put("system/etc/loop-a", "loop-b");
        links.put("system/etc/loop-b", "loop-a");
        links.put("apex/runtime", "/system/runtime");
        links.put("system/bin/filesystem-child", program);
        for (Map.Entry<String, String> link : links.entrySet()) {
            Os.symlink(link.getValue(), new File(root, link.getKey()).getAbsolutePath());
        }
        Map<String, String> libraries = new HashMap<>();
        libraries.put("libc.so", "liba10vm-source-libc.so");
        libraries.put("libdl.so", "liba10vm-source-libdl.so");
        File config = RuntimeConfiguration.prepare(runtime, seed, "filesystem-libraries", program, libraries, null);
        Map<String, String> env = new HashMap<>();
        env.put("A10VM_ROOTFS", root.getCanonicalPath());
        env.put("A10VM_HOST_ROOT", new File(program).getParent());
        env.put("A10VM_STATE_ROOT", seed.getCanonicalPath());
        env.put("A10VM_EXEC_LINKER", linker);
        env.put("A10VM_PROPERTIES", seed.getCanonicalPath());
        env.put("A10VM_LD_CONFIG", config.getCanonicalPath());
        JSONObject process = ProbeProcess.run(logs, "filesystem", Arrays.asList(linker, program, "parent", nonce), null, env);
        String text = process.getString("output");
        JSONObject checks = PropertyProbe.checks(text);
        boolean complete = true;
        for (String name : Arrays.asList("fs_ordinary_uid", "fs_absolute_open", "fs_absolute_symlink",
                "fs_relative_symlink", "fs_apex_symlink", "fs_parent_component", "fs_access", "fs_stat",
                "fs_lstat_symlink", "fs_readlink", "fs_missing_guest_no_host_file", "fs_symlink_loop",
                "fs_openat_dirfd", "fs_openat_absolute_symlink", "fs_chdir", "fs_physical_cwd", "fs_getcwd",
                "fs_relative_from_cwd", "fs_private_write", "fs_rename", "fs_unlink", "fs_mkdir_rmdir",
                "fs_child_argv0", "fs_child_paths", "fs_child_properties", "fs_child_cwd", "fs_guest_exec_chain",
                "fs_missing_exec", "bootstrap_identity_files")) {
            complete &= checks.optBoolean(name);
        }
        JSONObject identity = identities(text, nonce, allowed, seed);
        Map<String, String> negatives = new HashMap<>();
        negatives.put("child-euid", text.replaceFirst("(?m)^euid=[0-9]+$", "euid=0"));
        negatives.put("child-capabilities", text.replaceFirst("cap_eff=0{16}", "cap_eff=0000000000000001"));
        negatives.put("child-missing-context", text.replaceFirst("selinux=", "missing_context="));
        negatives.put("host-libc", text.replace(runtime.nativeFile("liba10vm-source-libc.so").getCanonicalPath(),
                "/system/lib64/libc.so"));
        JSONObject rejected = new JSONObject();
        boolean negativesPassed = true;
        for (Map.Entry<String, String> negative : negatives.entrySet()) {
            boolean passed = !negative.getValue().equals(text)
                    && !identities(negative.getValue(), nonce, allowed, seed).getBoolean("passed");
            negativesPassed &= passed;
            rejected.put(negative.getKey(), passed);
        }
        boolean passed = !process.getBoolean("timedOut") && process.getInt("exitCode") == 0
                && complete && !text.contains("\t0\n") && identity.getBoolean("passed") && negativesPassed
                && text.contains("filesystem_child_complete=1\n") && text.contains("filesystem_complete=1\n");
        return new JSONObject().put("gate", "G1-rootless-filesystem-exec").put("passed", passed)
                .put("rootRequired", false).put("completeG1", false).put("desktopVerified", false)
                .put("inputs", inputs).put("process", process).put("checks", checks)
                .put("identity", identity).put("validatorNegativeCases", rejected);
    }

    private static JSONObject identities(String text, String nonce, Set<String> allowed, File seed) throws Exception {
        Matcher matcher = Pattern.compile("filesystem_identity_begin=(parent|child)\\n(.*?)filesystem_identity_end=\\1\\n",
                Pattern.DOTALL).matcher(text);
        JSONArray processes = new JSONArray();
        Set<String> roles = new HashSet<>();
        Set<String> pids = new HashSet<>();
        boolean passed = true;
        while (matcher.find()) {
            String role = matcher.group(1);
            String block = matcher.group(2);
            Set<String> maps = LoaderProbe.executableMaps(block);
            String pid = GraphicsProbe.value(block, "pid");
            boolean ordinary = GraphicsProbe.appIdentity(block, nonce) && pid.matches("[1-9][0-9]*");
            for (String key : Arrays.asList("nonce", "pid", "uid", "euid", "cap_eff", "selinux")) {
                Matcher fields = Pattern.compile("(?m)^" + key + "=.*$").matcher(block);
                int count = 0;
                while (fields.find()) ++count;
                ordinary &= count == 1;
            }
            boolean isolated = maps.equals(allowed);
            boolean properties = RuntimeMappings.properties(block, seed, allowed, true, 2);
            passed &= roles.add(role) && pids.add(pid) && ordinary && isolated && properties;
            processes.put(new JSONObject().put("role", role).put("pid", pid)
                    .put("uid", GraphicsProbe.value(block, "uid")).put("euid", GraphicsProbe.value(block, "euid"))
                    .put("capEff", GraphicsProbe.value(block, "cap_eff")).put("selinux", GraphicsProbe.value(block, "selinux"))
                    .put("ordinaryIdentityPassed", ordinary).put("guestLibraryIsolationPassed", isolated)
                    .put("privateReadonlyMappingsPassed", properties).put("executableMappings", new JSONArray(maps)));
        }
        passed &= processes.length() == 2 && roles.equals(new HashSet<>(Arrays.asList("parent", "child"))) && pids.size() == 2;
        return new JSONObject().put("passed", passed).put("processes", processes);
    }
}
