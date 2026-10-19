package io.a10vm.containerprobe;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Real AOSP API linked into a test executable; matching libc integration is a later gate. */
final class PropertyApiProbe {
    private final LoaderProbe runtime;
    private final Set<String> allowed;

    PropertyApiProbe(LoaderProbe runtime, Set<String> allowed) {
        this.runtime = runtime;
        this.allowed = allowed;
    }

    JSONObject run(File logs, File instances, File config, String nonce) throws Exception {
        for (String transport : Arrays.asList("host", "guest")) {
            File seed = new File(instances, transport);
            File incomplete = new File(seed, "incomplete");
            Files.createDirectory(incomplete.toPath());
            Files.copy(new File(seed, "property_info").toPath(),
                    new File(incomplete, "property_info").toPath());
        }
        JSONArray runs = new JSONArray();
        boolean passed = true;
        String program = runtime.nativeFile("liba10vm-p2-property-api.so").getCanonicalPath();
        String linker = runtime.nativeFile("liba10vm-a10-linker.so").getCanonicalPath();
        String libc = runtime.nativeFile("liba10vm-a10-libc.so").getCanonicalPath();
        for (String mode : Arrays.asList("reader", "missing", "relative", "incomplete", "writer")) {
            JSONObject host = runCase(logs, instances, "host", mode, program, linker, null, nonce);
            JSONObject guest = runCase(logs, instances, "guest", mode, program, linker, config, nonce);
            Set<String> maps = LoaderProbe.executableMaps(guest.getString("output"));
            boolean isolated = allowed.containsAll(maps) && maps.contains(program)
                    && maps.contains(linker) && maps.contains(libc);
            Set<String> hostMaps = LoaderProbe.executableMaps(host.getString("output"));
            boolean hostDetected = !allowed.containsAll(hostMaps) && !hostMaps.contains(libc);
            boolean casePassed = completed(host, nonce, mode) && completed(guest, nonce, mode)
                    && isolated && hostDetected;
            passed &= casePassed;
            runs.put(new JSONObject().put("mode", mode).put("passed", casePassed)
                    .put("guest", guest).put("hostControl", host)
                    .put("guestLibraryIsolationPassed", isolated).put("hostControlDetected", hostDetected)
                    .put("checks", PropertyProbe.checks(guest.getString("output"))));
        }
        return new JSONObject().put("passed", passed).put("runtimeIntegration", false)
                .put("earlyEnvironmentSupplied", true).put("beforeExecutableConstructors", true)
                .put("heapMeasurement", "wrapped direct malloc/calloc/realloc calls in static inputs")
                .put("runs", runs);
    }

    private static JSONObject runCase(File logs, File instances, String transport, String mode,
            String program, String linker, File config, String nonce) throws Exception {
        File seed = new File(instances, transport);
        File directory = mode.equals("writer") ? new File(seed, "api-writer") : seed;
        List<String> command = new ArrayList<>();
        if (config != null) command.add(linker);
        command.addAll(Arrays.asList(program, mode, directory.getAbsolutePath(), nonce));
        Map<String, String> environment = new HashMap<>();
        if (mode.equals("reader")) environment.put("A10VM_PROPERTIES", seed.getAbsolutePath());
        else if (mode.equals("relative")) environment.put("A10VM_PROPERTIES", "relative");
        else if (mode.equals("incomplete")) {
            environment.put("A10VM_PROPERTIES", new File(seed, "incomplete").getAbsolutePath());
        }
        return ProbeProcess.run(logs, "api-" + transport + "-" + mode, command, config, environment);
    }

    private static boolean completed(JSONObject run, String nonce, String mode) throws Exception {
        String text = run.getString("output");
        JSONObject checks = PropertyProbe.checks(text);
        String[] common = {"api_early_no_heap_calls", "api_async_safe_format", "api_init_preserves_errno"};
        for (String name : common) if (!checks.optBoolean(name)) return false;
        String[] required = mode.equals("writer")
                ? new String[]{"api_writer_initially_empty", "api_writer_init", "api_writer_sdk29",
                        "api_writer_property_serial", "api_writer_global_serial", "api_writer_shared_mappings"}
                : new String[]{"api_reader_sdk29", "api_long_callback", "api_foreach",
                        "api_reader_readonly_mappings", "api_reinit_no_extra_mappings",
                        "api_instance_switch_rejected", "api_restore_instance"};
        for (String name : required) if (!checks.optBoolean(name)) return false;
        if (mode.equals("reader")) {
            if (!checks.optBoolean("api_preinit_survives_constructors")) return false;
        } else if (!mode.equals("writer")) {
            for (String name : new String[]{"api_uninitialized_empty", "api_uninitialized_wait",
                    "api_relative_writer_rejected", "api_missing_writer_rejected", "api_failed_init_retry"}) {
                if (!checks.optBoolean(name)) return false;
            }
        }
        return !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && GraphicsProbe.appIdentity(text, nonce)
                && mode.equals(GraphicsProbe.value(text, "api_mode"))
                && "29".equals(GraphicsProbe.value(text, "api_sdk"))
                && "1".equals(GraphicsProbe.value(text, "api_complete"));
    }
}
