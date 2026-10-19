package io.a10vm.containerprobe;

import android.content.Context;
import android.os.Build;
import android.os.Process;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Set;
import java.util.UUID;

/** Standalone AOSP properties; libc's own global properties remain the host control. */
final class PropertyProbe {
    private final Context context;

    PropertyProbe(Context context) { this.context = context; }

    JSONObject run(String nonce, boolean includeBootstrap, boolean includeDynamic, boolean includeCompanion,
            boolean includeFilesystem) throws Exception {
        LoaderProbe runtime = new LoaderProbe(context);
        JSONObject inputs = runtime.readInputs("properties-inputs.json");
        Set<String> allowed = runtime.verifyInputs(runtime.readInputs("inputs.json").getJSONArray("files"));
        allowed.addAll(runtime.verifyInputs(inputs.getJSONArray("files")));
        String program = runtime.nativeFile("liba10vm-p2-properties.so").getCanonicalPath();
        String linker = runtime.nativeFile("liba10vm-a10-linker.so").getCanonicalPath();
        File config = runtime.prepareRuntime("properties", false);
        File directory = new File(context.getFilesDir(), "properties");
        Files.createDirectories(directory.toPath());
        File instances = new File(directory, "run-" + UUID.randomUUID());
        Files.createDirectory(instances.toPath());
        JSONObject host;
        JSONObject guest;
        JSONObject api;
        JSONObject bootstrap = null;
        JSONObject dynamic = null;
        JSONObject companion = null;
        JSONObject filesystem = null;
        boolean removed;
        try {
            host = ProbeProcess.run(directory, "host",
                    Arrays.asList(program, "run", new File(instances, "host").getAbsolutePath(),
                            nonce, "/system/bin/linker64"), null);
            guest = ProbeProcess.run(directory, "guest",
                    Arrays.asList(linker, program, "run", new File(instances, "guest").getAbsolutePath(),
                            nonce, linker), config);
            api = new PropertyApiProbe(runtime, allowed).run(directory, instances, config, nonce);
            if (includeBootstrap) {
                bootstrap = new BootstrapProbe(runtime).run(directory, new File(instances, "guest"), nonce);
            }
            if (includeDynamic) {
                dynamic = new DynamicRuntimeProbe(runtime).run(directory, new File(instances, "guest"), nonce);
            }
            if (includeCompanion) {
                companion = new CompanionRuntimeProbe(runtime).run(directory, new File(instances, "guest"), nonce);
            }
            if (includeFilesystem) {
                filesystem = new FilesystemRuntimeProbe(runtime).run(directory, new File(instances, "guest"), nonce);
            }
        } finally {
            removeTree(instances);
            removed = !instances.exists();
        }
        String text = guest.getString("output");
        Set<String> mappings = LoaderProbe.executableMaps(text);
        boolean isolated = allowed.containsAll(mappings) && mappings.contains(program)
                && mappings.contains(linker)
                && mappings.contains(runtime.nativeFile("liba10vm-a10-libc.so").getCanonicalPath());
        Set<String> hostMaps = LoaderProbe.executableMaps(host.getString("output"));
        boolean hostDetected = !allowed.containsAll(hostMaps)
                && !hostMaps.contains(runtime.nativeFile("liba10vm-a10-libc.so").getCanonicalPath());
        JSONObject checks = checks(text);
        boolean passed = completed(guest, nonce) && completed(host, nonce) && isolated && hostDetected
                && api.getBoolean("passed") && removed
                && (bootstrap == null || bootstrap.getBoolean("passed"))
                && (dynamic == null || dynamic.getBoolean("passed"))
                && (companion == null || companion.getBoolean("passed"))
                && (filesystem == null || filesystem.getBoolean("passed"));
        return new JSONObject().put("gate", "P2-private-properties-component").put("passed", passed)
                .put("completeG1", false).put("runtimeIntegration", false).put("binderImplemented", false)
                .put("privatePropertiesComponentImplemented", true).put("hostSdk", Build.VERSION.SDK_INT)
                .put("appUid", Process.myUid()).put("targetSdk", context.getApplicationInfo().targetSdkVersion)
                .put("nonce", nonce).put("inputs", inputs).put("guest", guest).put("hostControl", host)
                .put("guestLibraryIsolationPassed", isolated).put("hostControlDetected", hostDetected)
                .put("checks", checks).put("api", api)
                .put("bootstrap", bootstrap == null ? JSONObject.NULL : bootstrap)
                .put("dynamic", dynamic == null ? JSONObject.NULL : dynamic)
                .put("companion", companion == null ? JSONObject.NULL : companion)
                .put("filesystem", filesystem == null ? JSONObject.NULL : filesystem)
                .put("instancesRemoved", removed)
                .put("guestExecutableMappings", new JSONArray(mappings));
    }

    private static boolean completed(JSONObject run, String nonce) throws Exception {
        String text = run.getString("output");
        JSONObject checks = checks(text);
        String[] required = {"private_sdk29", "reader_sdk29", "readonly_rewrite_rejected",
                "long_readonly_callback", "long_mutable_rejected", "cross_process_property_wait",
                "cross_process_global_wait", "property_wait_blocked", "global_wait_blocked",
                "property_serial_changed", "global_serial_changed", "reader_identity", "reader_exit",
                "reader_readonly_mappings", "reader_write_rejected", "property_timeout", "global_timeout",
                "writer_global_update_complete", "global_wait_ready",
                "instances_isolated", "reopen_unmapped", "failed_open_unmapped", "info_writable_rejected",
                "area_symlink_rejected", "writer_shared_mappings", "second_instance_unmapped"};
        for (String name : required) if (!checks.optBoolean(name)) return false;
        return !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && GraphicsProbe.appIdentity(text, nonce)
                && "29".equals(GraphicsProbe.value(text, "private_sdk"))
                && Integer.toString(Build.VERSION.SDK_INT).equals(GraphicsProbe.value(text, "visible_sdk"))
                && GraphicsProbe.value(text, "visible_sdk").equals(GraphicsProbe.value(text, "host_sdk_after"))
                && Integer.toString(Process.myUid()).equals(GraphicsProbe.value(text, "reader_uid"))
                && !GraphicsProbe.value(text, "pid").equals(GraphicsProbe.value(text, "reader_pid"))
                && "1".equals(GraphicsProbe.value(text, "probe_complete"));
    }

    static JSONObject checks(String text) throws Exception {
        JSONObject checks = new JSONObject();
        for (String line : text.split("\n")) {
            String[] fields = line.split("\t");
            if (fields.length == 3 && fields[0].equals("CHECK")) {
                checks.put(fields[1], fields[2].equals("1"));
            }
        }
        return checks;
    }

    private static void removeTree(File directory) throws Exception {
        File[] children = directory.listFiles();
        if (children == null) throw new IllegalStateException("Probe directory listing failed: " + directory);
        for (File child : children) {
            if (Files.isDirectory(child.toPath(), java.nio.file.LinkOption.NOFOLLOW_LINKS)) removeTree(child);
            else Files.delete(child.toPath());
        }
        Files.delete(directory.toPath());
    }
}
