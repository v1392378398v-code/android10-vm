package io.a10vm.containerprobe;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/** Source-built static Bionic; dynamic linker/libc integration has a separate gate. */
final class BootstrapProbe {
    private final LoaderProbe runtime;

    BootstrapProbe(LoaderProbe runtime) { this.runtime = runtime; }

    JSONObject run(File logs, File seed, String nonce) throws Exception {
        JSONObject inputs = runtime.readInputs("runtime-inputs.json");
        runtime.verifyInputs(inputs.getJSONArray("files"));
        String program = runtime.nativeFile("liba10vm-p2-bootstrap.so").getCanonicalPath();
        File incomplete = new File(seed, "bootstrap-incomplete");
        Files.createDirectory(incomplete.toPath());
        Files.copy(new File(seed, "property_info").toPath(),
                new File(incomplete, "property_info").toPath());
        JSONArray runs = new JSONArray();
        boolean passed = true;
        for (String mode : Arrays.asList("reader", "missing", "relative", "incomplete")) {
            Map<String, String> environment = new HashMap<>();
            if (mode.equals("reader")) environment.put("A10VM_PROPERTIES", seed.getAbsolutePath());
            else if (mode.equals("relative")) environment.put("A10VM_PROPERTIES", "relative");
            else if (mode.equals("incomplete")) {
                environment.put("A10VM_PROPERTIES", incomplete.getAbsolutePath());
            }
            JSONObject result = ProbeProcess.run(logs, "bootstrap-" + mode,
                    Arrays.asList(program, mode, nonce), null, environment);
            String text = result.getString("output");
            Set<String> maps = LoaderProbe.executableMaps(text);
            boolean isolated = maps.size() == 1 && maps.contains(program);
            boolean propertyMaps = RuntimeMappings.properties(text, seed,
                    java.util.Collections.singleton(program), mode.equals("reader"), 1);
            boolean casePassed = completed(result, mode, nonce) && isolated && propertyMaps;
            passed &= casePassed;
            runs.put(new JSONObject().put("mode", mode).put("passed", casePassed)
                    .put("process", result).put("checks", PropertyProbe.checks(text))
                    .put("ownExecutableOnly", isolated).put("privateReadonlyMappingsPassed", propertyMaps)
                    .put("executableMappings", new JSONArray(maps)));
        }
        return new JSONObject().put("gate", "P2-static-bionic-bootstrap").put("passed", passed)
                .put("inputs", inputs).put("staticBionicBootstrap", true)
                .put("dynamicRuntimeIntegrated", false).put("binderImplemented", false)
                .put("concurrentAllocatorVerified", false).put("runs", runs);
    }

    private static boolean completed(JSONObject run, String mode, String nonce) throws Exception {
        String text = run.getString("output");
        JSONObject checks = PropertyProbe.checks(text);
        String[] common = {"bootstrap_init_order", "bootstrap_key_create", "bootstrap_thread_create",
                "bootstrap_thread_join", "bootstrap_tls_errno_isolation", "bootstrap_thread_destructors",
                "bootstrap_key_delete", "bootstrap_identity_files", "bootstrap_stdio_buffered"};
        for (String name : common) if (!checks.optBoolean(name)) return false;
        String[] required = mode.equals("reader")
                ? new String[]{"bootstrap_preinit_sdk29", "bootstrap_constructor_sdk29",
                        "bootstrap_property_reinit_errno"}
                : new String[]{"bootstrap_no_host_property_fallback", "bootstrap_uninitialized_wait"};
        for (String name : required) if (!checks.optBoolean(name)) return false;
        String sdk = mode.equals("reader") ? "29" : "";
        for (String stage : Arrays.asList("preinit", "constructor", "main")) {
            if (!sdk.equals(GraphicsProbe.value(text, stage + "_sdk"))) return false;
        }
        return !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && GraphicsProbe.appIdentity(text, nonce)
                && mode.equals(GraphicsProbe.value(text, "bootstrap_mode"))
                && !text.contains("\t0\n") && !text.contains("/dev/__properties__")
                && text.contains("thread_rounds=2\nkey_destructors=2\ncpp_destructors=2\n")
                && text.contains("bootstrap_complete=1\nfini_complete=1\nstdio_flush_complete=1\n");
    }

}
