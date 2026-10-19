package io.a10vm.containerprobe;

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

/** Source-built Android 10 loader/libc, exercised inside the ordinary APK UID. */
final class DynamicRuntimeProbe {
    private final LoaderProbe runtime;

    DynamicRuntimeProbe(LoaderProbe runtime) { this.runtime = runtime; }

    JSONObject run(File logs, File seed, String nonce) throws Exception {
        JSONObject inputs = runtime.readInputs("dynamic-inputs.json");
        Set<String> allowed = runtime.verifyInputs(inputs.getJSONArray("files"));
        String program = runtime.nativeFile("liba10vm-p2-dynamic.so").getCanonicalPath();
        String linker = runtime.nativeFile("liba10vm-source-linker.so").getCanonicalPath();
        String module = runtime.nativeFile("liba10vm-tls-test.so").getCanonicalPath();
        Set<String> expectedMaps = new HashSet<>(allowed);
        expectedMaps.remove(module);
        File config = prepare(seed, "dynamic-complete", program, false);
        File incomplete = new File(seed, "dynamic-incomplete");
        Files.createDirectory(incomplete.toPath());
        Files.copy(new File(seed, "property_info").toPath(),
                new File(incomplete, "property_info").toPath());
        JSONArray runs = new JSONArray();
        boolean passed = true;
        for (String mode : Arrays.asList("reader", "missing", "relative", "incomplete")) {
            Map<String, String> env = new HashMap<>();
            env.put("A10VM_LD_CONFIG", config.getAbsolutePath());
            if (mode.equals("reader")) env.put("A10VM_PROPERTIES", seed.getAbsolutePath());
            else if (mode.equals("relative")) env.put("A10VM_PROPERTIES", "relative");
            else if (mode.equals("incomplete")) env.put("A10VM_PROPERTIES", incomplete.getAbsolutePath());
            JSONObject result = ProbeProcess.run(logs, "dynamic-" + mode,
                    Arrays.asList(linker, program, mode, nonce, module), null, env);
            String text = result.getString("output");
            Set<String> maps = LoaderProbe.executableMaps(text);
            boolean isolated = maps.equals(expectedMaps);
            boolean properties = RuntimeMappings.properties(text, seed, expectedMaps, mode.equals("reader"), 4);
            boolean casePassed = completed(result, mode, nonce) && isolated && properties
                    && linker.equals(new File(GraphicsProbe.value(text, "source_linker")).getCanonicalPath())
                    && runtime.nativeFile("liba10vm-source-libc.so").getCanonicalPath().equals(
                            new File(GraphicsProbe.value(text, "source_libc")).getCanonicalPath());
            passed &= casePassed;
            runs.put(new JSONObject().put("mode", mode).put("passed", casePassed).put("process", result)
                    .put("checks", PropertyProbe.checks(text)).put("guestLibraryIsolationPassed", isolated)
                    .put("privateReadonlyMappingsPassed", properties).put("executableMappings", new JSONArray(maps)));
        }
        File bad = new File(seed, "dynamic-bad.config");
        Files.write(bad.toPath(), "[wrong-section]\nnamespace.default.isolated = true\n"
                .getBytes(StandardCharsets.UTF_8));
        File missing = prepare(seed, "dynamic-missing-libc", program, true);
        Map<String, String> failures = new java.util.LinkedHashMap<>();
        failures.put("missing-config", null);
        failures.put("relative-config", "relative");
        failures.put("bad-config", bad.getAbsolutePath());
        failures.put("missing-libc", missing.getAbsolutePath());
        JSONArray rejected = new JSONArray();
        for (Map.Entry<String, String> failure : failures.entrySet()) {
            Map<String, String> env = new HashMap<>();
            env.put("A10VM_PROPERTIES", seed.getAbsolutePath());
            if (failure.getValue() != null) env.put("A10VM_LD_CONFIG", failure.getValue());
            JSONObject result = ProbeProcess.run(logs, "dynamic-" + failure.getKey(),
                    Arrays.asList(linker, program, "reader", nonce, module), null, env);
            String diagnostic = failure.getKey().equals("missing-libc") ? "libc.so"
                    : failure.getKey().equals("bad-config") ? "private linker configuration was rejected"
                    : "requires an existing absolute private configuration";
            String text = result.getString("output");
            boolean casePassed = !result.getBoolean("timedOut") && result.getInt("exitCode") != 0
                    && text.contains(diagnostic) && !text.contains("dynamic_mode=")
                    && (!failure.getKey().equals("missing-libc") || text.contains("not found"));
            passed &= casePassed;
            rejected.put(new JSONObject().put("mode", failure.getKey()).put("passed", casePassed)
                    .put("process", result));
        }
        return new JSONObject().put("gate", "P2-source-dynamic-runtime").put("passed", passed)
                .put("completeG1", false).put("loaderFromSource", true).put("dynamicRuntimeIntegrated", true)
                .put("concurrentAllocatorVerified", passed).put("binderImplemented", false)
                .put("inputs", inputs).put("runs", runs).put("rejected", rejected);
    }

    private File prepare(File seed, String name, String program, boolean missingLibc) throws Exception {
        Map<String, String> libraries = new HashMap<>();
        libraries.put("libc.so", "liba10vm-source-libc.so");
        libraries.put("libdl.so", "liba10vm-source-libdl.so");
        return RuntimeConfiguration.prepare(runtime, seed, name, program, libraries,
                missingLibc ? "libc.so" : null);
    }

    private static boolean completed(JSONObject run, String mode, String nonce) throws Exception {
        String text = run.getString("output");
        JSONObject checks = PropertyProbe.checks(text);
        for (String name : Arrays.asList("dynamic_property_init_order", "dynamic_shared_globals",
                "dynamic_loader_libc_distinct", "dynamic_exec_child_properties",
                "dynamic_exec_child_runtime", "dynamic_exec_chain", "bootstrap_key_create", "bootstrap_thread_create",
                "bootstrap_thread_join", "bootstrap_tls_errno_isolation", "bootstrap_thread_destructors",
                "bootstrap_key_delete", "dynamic_allocator_barrier", "dynamic_allocator_concurrent",
                "dynamic_dlopen", "dynamic_dlsym", "dynamic_tls_main_initialization",
                "dynamic_tls_existing_thread", "dynamic_tls_generation", "dynamic_tls_dso_pinned",
                "dynamic_tls_dso_unloaded", "bootstrap_identity_files", "dynamic_stdio_buffered")) {
            if (!checks.optBoolean(name)) return false;
        }
        String sdk = mode.equals("reader") ? "29" : "";
        if (!"".equals(GraphicsProbe.value(text, "preinit_sdk"))) return false;
        for (String stage : Arrays.asList("constructor", "main")) {
            if (!sdk.equals(GraphicsProbe.value(text, stage + "_sdk"))) return false;
        }
        return !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && GraphicsProbe.appIdentity(text, nonce) && mode.equals(GraphicsProbe.value(text, "dynamic_mode"))
                && !text.contains("\t0\n") && !text.contains("/dev/__properties__")
                && text.contains("thread_rounds=2\nkey_destructors=2\ncpp_destructors=2\n")
                && "1".equals(GraphicsProbe.value(text, "dynamic_exec_child_started"))
                && "1".equals(GraphicsProbe.value(text, "dynamic_exec_child_complete"))
                && mode.equals(GraphicsProbe.value(text, "dynamic_exec_child_mode"))
                && text.contains("allocator_workers=4\nallocator_rounds_per_worker=64\n")
                && text.contains("dynamic_tls_rounds=2\ndynamic_tls_destructors=2\ndynamic_module_unloads=2\n")
                && text.contains("dynamic_complete=1\ndynamic_fini_complete=1\ndynamic_stdio_flush_complete=1\n");
    }
}
