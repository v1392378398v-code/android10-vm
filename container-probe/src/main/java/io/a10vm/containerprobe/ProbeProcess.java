package io.a10vm.containerprobe;

import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

final class ProbeProcess {
    static JSONObject run(File directory, String label, List<String> command, File config)
            throws Exception {
        return run(directory, label, command, config, java.util.Collections.emptyMap());
    }

    static JSONObject run(File directory, String label, List<String> command, File config,
            Map<String, String> extraEnvironment) throws Exception {
        File output = new File(directory, label + ".log");
        ProcessBuilder builder = builder(directory, output, command, config);
        builder.environment().putAll(extraEnvironment);
        long start = SystemClock.elapsedRealtime();
        Process process = builder.start();
        try {
            boolean exited = process.waitFor(8, TimeUnit.SECONDS);
            if (!exited) {
                process.destroyForcibly();
                if (!process.waitFor(2, TimeUnit.SECONDS)) {
                    throw new IllegalStateException("Probe child did not exit after termination");
                }
            }
            return new JSONObject().put("command", new JSONArray(command))
                    .put("config", config == null ? JSONObject.NULL
                            : new String(Files.readAllBytes(config.toPath()), StandardCharsets.UTF_8))
                    .put("elapsedMs", SystemClock.elapsedRealtime() - start)
                    .put("timedOut", !exited).put("exitCode", process.exitValue())
                    .put("output", new String(Files.readAllBytes(output.toPath()), StandardCharsets.UTF_8));
        } finally {
            if (process.isAlive()) process.destroyForcibly();
            Files.deleteIfExists(output.toPath());
        }
    }

    static ProcessBuilder builder(File directory, File output, List<String> command, File config) {
        ProcessBuilder builder = new ProcessBuilder(command).directory(directory)
                .redirectErrorStream(true).redirectOutput(output);
        Map<String, String> environment = builder.environment();
        environment.clear();
        environment.put("PATH", "/system/bin");
        environment.put("TMPDIR", directory.getAbsolutePath());
        if (config != null) environment.put("LD_CONFIG_FILE", config.getAbsolutePath());
        return builder;
    }
}
