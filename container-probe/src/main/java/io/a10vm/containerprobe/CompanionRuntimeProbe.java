package io.a10vm.containerprobe;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Math/C++/exception behavior on the private source-built loader and libraries. */
final class CompanionRuntimeProbe {
    private final LoaderProbe runtime;

    CompanionRuntimeProbe(LoaderProbe runtime) { this.runtime = runtime; }

    JSONObject run(File logs, File seed, String nonce) throws Exception {
        JSONObject inputs = runtime.readInputs("companion-inputs.json");
        Set<String> expected = runtime.verifyInputs(inputs.getJSONArray("files"));
        JSONObject dynamic = runtime.readInputs("dynamic-inputs.json");
        runtime.verifyInputs(dynamic.getJSONArray("files"));
        String program = runtime.nativeFile("liba10vm-p2-companion.so").getCanonicalPath();
        String linker = runtime.nativeFile("liba10vm-source-linker.so").getCanonicalPath();
        String late = runtime.nativeFile("liba10vm-late-test.so").getCanonicalPath();
        expected.remove(late);
        expected.add(linker);
        expected.add(runtime.nativeFile("liba10vm-source-libc.so").getCanonicalPath());
        expected.add(runtime.nativeFile("liba10vm-source-libdl.so").getCanonicalPath());
        Map<String, String> libraries = new HashMap<>();
        libraries.put("libc.so", "liba10vm-source-libc.so");
        libraries.put("libdl.so", "liba10vm-source-libdl.so");
        libraries.put("libm.so", "liba10vm-source-libm.so");
        libraries.put("libc++.so", "liba10vm-source-libcxx.so");
        libraries.put("libunwind.so", "liba10vm-source-libunwind.so");
        libraries.put("liba10vm-exceptions.so", "liba10vm-exceptions.so");
        File config = RuntimeConfiguration.prepare(runtime, seed, "companion-complete", program, libraries, null);
        JSONArray runs = new JSONArray();
        boolean passed = true;
        for (int round = 0; round < 2; ++round) {
            JSONObject result = execute(logs, "normal-" + round, "normal", nonce, program, linker, late, seed, config);
            String text = result.getString("output");
            Set<String> maps = LoaderProbe.executableMaps(text);
            boolean isolated = maps.equals(expected);
            boolean properties = RuntimeMappings.properties(text, seed, expected, true, 2);
            boolean casePassed = completed(result, nonce, inputs) && isolated && properties;
            for (String key : Arrays.asList("source_libc", "source_libm", "source_cxx", "source_unwind")) {
                String file = key.equals("source_cxx") ? "liba10vm-source-libcxx.so"
                        : key.equals("source_unwind") ? "liba10vm-source-libunwind.so"
                        : "liba10vm-" + key.replace('_', '-') + ".so";
                casePassed &= runtime.nativeFile(file).getCanonicalPath().equals(
                        new File(GraphicsProbe.value(text, key)).getCanonicalPath());
            }
            passed &= casePassed;
            runs.put(new JSONObject().put("passed", casePassed).put("process", result)
                    .put("checks", PropertyProbe.checks(text)).put("guestLibraryIsolationPassed", isolated)
                    .put("privateReadonlyMappingsPassed", properties).put("executableMappings", new JSONArray(maps)));
        }
        JSONArray termination = new JSONArray();
        for (String mode : Arrays.asList("uncaught", "noexcept")) {
            JSONObject result = execute(logs, mode, mode, nonce, program, linker, late, seed, config);
            String text = result.getString("output");
            boolean casePassed = !result.getBoolean("timedOut") && result.getInt("exitCode") == 86
                    && text.contains("companion_mode=" + mode + "\nterminate_handler_called=1\n")
                    && !text.contains("companion_complete=");
            passed &= casePassed;
            termination.put(new JSONObject().put("mode", mode).put("passed", casePassed).put("process", result));
        }
        JSONArray rejected = new JSONArray();
        for (String missing : Arrays.asList("libm.so", "libc++.so", "libunwind.so")) {
            File absent = RuntimeConfiguration.prepare(runtime, seed, "companion-missing-" + missing,
                    program, libraries, missing);
            JSONObject result = execute(logs, "missing-" + missing, "normal", nonce, program, linker, late, seed, absent);
            String text = result.getString("output");
            boolean casePassed = !result.getBoolean("timedOut") && result.getInt("exitCode") != 0
                    && text.contains(missing) && text.contains("not found") && !text.contains("companion_mode=");
            passed &= casePassed;
            rejected.put(new JSONObject().put("missing", missing).put("passed", casePassed).put("process", result));
        }
        return new JSONObject().put("gate", "P2-source-companion-runtime").put("passed", passed)
                .put("completeG1", false).put("librariesFromSource", true).put("aarch64LlvmUnwindAdaptation", true)
                .put("binary128SincoslCorrection", true)
                .put("binderImplemented", false).put("inputs", inputs).put("runs", runs)
                .put("termination", termination).put("rejected", rejected);
    }

    private JSONObject execute(File logs, String label, String mode, String nonce, String program,
            String linker, String late, File seed, File config) throws Exception {
        Map<String, String> env = new HashMap<>();
        env.put("A10VM_PROPERTIES", seed.getAbsolutePath());
        env.put("A10VM_LD_CONFIG", config.getAbsolutePath());
        return ProbeProcess.run(logs, "companion-" + label,
                Arrays.asList(linker, program, mode, nonce, late), null, env);
    }

    private static boolean completed(JSONObject run, String nonce, JSONObject inputs) throws Exception {
        String text = run.getString("output");
        JSONObject checks = PropertyProbe.checks(text);
        Set<String> required = new HashSet<>();
        JSONArray names = inputs.getJSONArray("requiredChecks");
        for (int i = 0; i < names.length(); ++i) {
            required.add(names.getString(i));
            if (!checks.optBoolean(names.getString(i))) return false;
        }
        if (checks.length() != required.size()) return false;
        return !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && GraphicsProbe.appIdentity(text, nonce) && !text.contains("\t0\n")
                && !text.contains("/dev/__properties__") && "normal".equals(GraphicsProbe.value(text, "companion_mode"))
                && "29".equals(GraphicsProbe.value(text, "main_sdk"))
                && Integer.toString(inputs.getInt("libcppVersion")).equals(GraphicsProbe.value(text, "libcpp_version"))
                && "113".equals(GraphicsProbe.value(text, "math_long_double_bits"))
                && "4".equals(GraphicsProbe.value(text, "cxx_workers"))
                && "4".equals(GraphicsProbe.value(text, "cxx_tls_destructors"))
                && "2".equals(GraphicsProbe.value(text, "exception_late_rounds"))
                && text.split("late_module_fini=1\n", -1).length == 3
                && text.contains("companion_complete=1\ncompanion_fini_complete=1\n");
    }
}
