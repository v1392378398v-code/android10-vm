package io.a10vm.containerprobe;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/** Runs the private Binder stack as child processes of the ordinary APK UID. */
final class BinderRuntimeProbe {
    private final Context context;

    BinderRuntimeProbe(Context context) { this.context = context; }

    JSONObject run(String nonce) throws Exception {
        LoaderProbe runtime = new LoaderProbe(context);
        JSONObject inputs = runtime.readInputs("binder-inputs.json");
        runtime.verifyInputs(inputs.getJSONArray("files"));
        int appUid = android.os.Process.myUid();
        File directory = new File(context.getFilesDir(), "binder-" + UUID.randomUUID());
        Files.createDirectory(directory.toPath());
        List<Child> children = new ArrayList<>();
        JSONArray clientChecks = new JSONArray();
        JSONArray lifecycleChecks = new JSONArray();
        JSONArray finalStats = new JSONArray();
        Object seedSummary = JSONObject.NULL;
        boolean resourcesReclaimed = false;
        boolean brokerDisconnectNormalExit = false;
        boolean passed = false;
        String error = null;
        String diagnostics = "";

        try {
            require(appUid >= 10000, "Instrumentation is not running under an app UID");
            File seed = new File(directory, "properties");
            JSONObject seedRun = ProbeProcess.run(directory, "binder-property-seed",
                    Arrays.asList(runtime.nativeFile("liba10vm-p2-properties.so").getCanonicalPath(),
                            "run", seed.getAbsolutePath(), nonce, "/system/bin/linker64"), null);
            String seedText = seedRun.getString("output");
            boolean seedPassed = !seedRun.getBoolean("timedOut") && seedRun.getInt("exitCode") == 0
                    && GraphicsProbe.appIdentity(seedText, nonce)
                    && seedText.contains("CHECK\tsdk_seed\t1\n")
                    && seedText.contains("CHECK\tprivate_sdk29\t1\n");
            seedSummary = new JSONObject().put("passed", seedPassed)
                    .put("exitCode", seedRun.getInt("exitCode"))
                    .put("uid", GraphicsProbe.value(seedText, "uid"))
                    .put("selinux", GraphicsProbe.value(seedText, "selinux"));
            require(seedPassed, "Private SDK 29 property seed failed: " + seedText);

            String linker = runtime.nativeFile("liba10vm-source-linker.so").getCanonicalPath();
            String program = runtime.nativeFile("liba10vm-p2-binder-probe.so").getCanonicalPath();
            String brokerProgram = runtime.nativeFile("liba10vm-p2-binder-broker.so").getCanonicalPath();
            Map<String, String> libraries = new LinkedHashMap<>();
            libraries.put("libc.so", "liba10vm-source-libc.so");
            libraries.put("libdl.so", "liba10vm-source-libdl.so");
            libraries.put("libm.so", "liba10vm-source-libm.so");
            libraries.put("libc++.so", "liba10vm-source-libcxx.so");
            libraries.put("libunwind.so", "liba10vm-source-libunwind.so");
            libraries.put("liblog.so", "liba10vm-source-liblog.so");
            libraries.put("libbase.so", "liba10vm-source-libbase.so");
            libraries.put("libcutils.so", "liba10vm-source-libcutils.so");
            libraries.put("libutils.so", "liba10vm-source-libutils.so");
            libraries.put("libbinderthreadstate.so", "liba10vm-source-libbinderthreadstate.so");
            libraries.put("liba10binder.so", "liba10vm-private-binder-transport.so");
            libraries.put("libbinder.so", "liba10vm-source-libbinder.so");
            File config = RuntimeConfiguration.prepare(runtime, seed, "binder-runtime", program, libraries, null);
            File socket = new File(directory, "binder.sock");
            Map<String, String> environment = new HashMap<>();
            environment.put("A10VM_PROPERTIES", seed.getAbsolutePath());
            environment.put("A10VM_LD_CONFIG", config.getAbsolutePath());
            environment.put("A10VM_BINDER_PATH", socket.getAbsolutePath());

            Child broker = start(children, directory, "broker", linker, brokerProgram,
                    new String[]{socket.getAbsolutePath()}, environment);
            String brokerText = waitMarker(broker, "binder_broker_ready=1", 8);
            checkIdentity(broker, brokerText, "binder_broker_pid", "binder_broker_uid", appUid, null);

            Child registry = start(children, directory, "registry", linker, program,
                    new String[]{"registry", socket.getAbsolutePath()}, environment);
            String registryText = waitMarker(registry, "binder_registry_ready=1", 8);
            checkIdentity(registry, registryText, "binder_pid", "binder_uid", appUid, "29");
            boolean registryPassed = checkPassed(registryText, "registry_context");
            lifecycleChecks.put(new JSONObject().put("name", "registry_context").put("passed", registryPassed));
            require(registryPassed, "Registry context manager did not start: " + registryText);

            Child service = start(children, directory, "service", linker, program,
                    new String[]{"service", socket.getAbsolutePath()}, environment);
            String serviceText = waitMarker(service, "binder_service_ready=1", 8);
            checkIdentity(service, serviceText, "binder_pid", "binder_uid", appUid, "29");
            String servicePid = GraphicsProbe.value(serviceText, "binder_pid");
            require(parseLong(servicePid) > 0, "Binder service did not report a PID: " + serviceText);
            boolean servicePassed = checkPassed(serviceText, "service_registered");
            lifecycleChecks.put(new JSONObject().put("name", "service_registered").put("passed", servicePassed));
            require(servicePassed, "Binder service registration failed: " + serviceText);

            Map<String, String> clientEnvironment = new HashMap<>(environment);
            clientEnvironment.put("A10VM_SERVICE_PID", servicePid);
            Child client = start(children, directory, "client", linker, program,
                    new String[]{"client", socket.getAbsolutePath()}, clientEnvironment);
            String clientText = waitMarker(client, "binder_client_complete=", 25);
            checkIdentity(client, clientText, "binder_pid", "binder_uid", appUid, "29");
            boolean clientPassed = checkClient(clientText, inputs.getJSONArray("requiredChecks"), clientChecks)
                    && clientText.contains("binder_client_complete=1\n")
                    && clientText.contains("binder_client_returned=1\n");
            require(clientPassed, "Binder client checks failed: " + clientText);
            waitForExit(client, 5, true);
            waitForExit(service, 3, true);

            JSONArray afterService = waitForStats(directory, linker, program, socket, environment,
                    values -> values.optLong(4, -1) == 0, 3);
            Child registryChild = registry;
            registryChild.process.destroy();
            waitForExit(registryChild, 3, false);
            finalStats = waitForStats(directory, linker, program, socket, environment,
                    BinderRuntimeProbe::allProcessesReclaimed, 3);
            resourcesReclaimed = allProcessesReclaimed(finalStats);
            require(resourcesReclaimed, "Binder resources remained after client and registry exit: " + finalStats);

            Child looper = start(children, directory, "disconnect", linker, program,
                    new String[]{"looper", socket.getAbsolutePath()}, environment);
            String looperText = waitMarker(looper, "binder_looper_ready=1", 8);
            checkIdentity(looper, looperText, "binder_pid", "binder_uid", appUid, "29");
            Thread.sleep(50);
            broker.process.destroy();
            waitForExit(broker, 3, true);
            String brokerStopped = read(broker.log);
            waitForExit(looper, 3, true);
            String looperStopped = read(looper.log);
            brokerDisconnectNormalExit = brokerStopped.contains("binder_broker_stopped=1\n")
                    && looperStopped.contains("binder_looper_returned=1\n");
            require(brokerDisconnectNormalExit, "Broker disconnect did not return the Binder looper normally");
            passed = seedPassed && registryPassed && servicePassed && clientPassed && resourcesReclaimed
                    && brokerDisconnectNormalExit && afterService.optLong(4, -1) == 0;
        } catch (Exception failure) {
            error = failure.toString();
            diagnostics = diagnosticTails(children);
        } finally {
            for (int i = children.size() - 1; i >= 0; --i) {
                Child child = children.get(i);
                if (child.process.isAlive()) child.process.destroyForcibly();
                child.process.waitFor(2, TimeUnit.SECONDS);
            }
        }

        JSONArray processResults = new JSONArray();
        for (Child child : children) processResults.put(processSummary(child, appUid));
        boolean cleaned = removeTree(directory);
        JSONObject report = new JSONObject().put("gate", "P2-private-binder")
                .put("passed", passed && cleaned).put("completeG2", false).put("sourceBuilt", true)
                .put("appUid", appUid).put("ordinaryAppUid", appUid >= 10000).put("nonce", nonce)
                .put("inputs", inputs).put("propertySeed", seedSummary)
                .put("requiredClientCheckCount", inputs.getJSONArray("requiredChecks").length())
                .put("clientChecks", clientChecks).put("lifecycleChecks", lifecycleChecks)
                .put("processes", processResults).put("finalStats", finalStats)
                .put("resourcesReclaimed", resourcesReclaimed)
                .put("brokerDisconnectNormalExit", brokerDisconnectNormalExit)
                .put("workDirectoryRemoved", cleaned)
                .put("diagnostics", diagnostics)
                .put("error", error == null ? JSONObject.NULL : error);
        return report;
    }

    private static Child start(List<Child> children, File directory, String role, String linker,
            String program, String[] arguments, Map<String, String> environment) throws Exception {
        List<String> command = new ArrayList<>();
        command.add(linker);
        command.add(program);
        command.addAll(Arrays.asList(arguments));
        File output = new File(directory, role + ".log");
        ProcessBuilder builder = ProbeProcess.builder(directory, output, command, null);
        builder.environment().putAll(environment);
        Child child = new Child(role, builder.start(), output);
        children.add(child);
        return child;
    }

    private static String waitMarker(Child child, String marker, int timeoutSeconds) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(timeoutSeconds);
        while (System.nanoTime() < deadline) {
            String text = read(child.log);
            if (text.contains(marker)) return text;
            if (!child.process.isAlive()) {
                for (int retry = 0; retry < 10; ++retry) {
                    Thread.sleep(20);
                    text = read(child.log);
                    if (text.contains(marker)) return text;
                }
                throw new IllegalStateException(child.role + " exited before " + marker + ": " + text);
            }
            Thread.sleep(20);
        }
        throw new IllegalStateException(child.role + " timed out waiting for " + marker + ": " + read(child.log));
    }

    private static void checkIdentity(Child child, String text, String pidKey, String uidKey,
            int appUid, String sdk) {
        int uid = parseInt(GraphicsProbe.value(text, uidKey));
        long pid = parseLong(GraphicsProbe.value(text, pidKey));
        if (uid != appUid || pid <= 0
                || (sdk != null && !sdk.equals(GraphicsProbe.value(text, "binder_sdk")))) {
            throw new IllegalStateException(child.role + " identity mismatch: " + text);
        }
    }

    private static boolean checkPassed(String text, String name) {
        return text.contains("CHECK\t" + name + "\t1\n");
    }

    private static boolean checkClient(String text, JSONArray required, JSONArray output) throws Exception {
        Set<String> expected = new HashSet<>();
        for (int i = 0; i < required.length(); ++i) expected.add(required.getString(i));
        Set<String> seen = new HashSet<>();
        boolean passed = true;
        for (String line : text.split("\n")) {
            String[] fields = line.split("\t");
            if (fields.length != 3 || !fields[0].equals("CHECK")) continue;
            boolean checkPassed = fields[2].equals("1");
            passed &= expected.contains(fields[1]) && seen.add(fields[1]) && checkPassed;
            output.put(new JSONObject().put("name", fields[1]).put("passed", checkPassed));
        }
        return passed && seen.equals(expected);
    }

    private static JSONArray waitForStats(File directory, String linker, String program, File socket,
            Map<String, String> environment, StatsPredicate predicate, int timeoutSeconds) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(timeoutSeconds);
        JSONArray stats;
        do {
            JSONObject run = ProbeProcess.run(directory, "binder-inspect",
                    Arrays.asList(linker, program, "inspect", socket.getAbsolutePath()), null, environment);
            String text = run.getString("output");
            if (run.getBoolean("timedOut") || run.getInt("exitCode") != 0) {
                throw new IllegalStateException("Binder inspector failed: " + text);
            }
            stats = parseStats(text);
            if (predicate.matches(stats)) return stats;
            Thread.sleep(20);
        } while (System.nanoTime() < deadline);
        throw new IllegalStateException("Binder resource state timed out: " + stats);
    }

    private static JSONArray parseStats(String text) throws Exception {
        for (String line : text.split("\n")) {
            if (!line.startsWith("STATS\t")) continue;
            JSONArray values = new JSONArray();
            for (String field : line.substring(6).split("\t")) values.put(Long.parseLong(field));
            if (values.length() != 28) throw new IllegalStateException("Expected 28 Binder stats, got " + values.length());
            return values;
        }
        throw new IllegalStateException("Binder inspector did not emit STATS: " + text);
    }

    private static boolean allProcessesReclaimed(JSONArray stats) {
        if (stats.length() != 28) return false;
        for (int i = 0; i < 8; ++i) if (stats.optLong(i, -1) != 0) return false;
        return stats.optLong(13, -1) == 0 && stats.optLong(14, -1) == 0;
    }

    private static void waitForExit(Child child, int timeoutSeconds, boolean requireSuccess) throws Exception {
        if (!child.process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
            child.process.destroyForcibly();
            throw new IllegalStateException(child.role + " did not exit within " + timeoutSeconds + " seconds");
        }
        if (requireSuccess && child.process.exitValue() != 0) {
            throw new IllegalStateException(child.role + " exited with " + child.process.exitValue() + ": " + read(child.log));
        }
    }

    private static JSONObject processSummary(Child child, int appUid) throws Exception {
        String text = read(child.log);
        String uidKey = child.role.equals("broker") ? "binder_broker_uid" : "binder_uid";
        String pidKey = child.role.equals("broker") ? "binder_broker_pid" : "binder_pid";
        int uid = parseInt(GraphicsProbe.value(text, uidKey));
        long pid = parseLong(GraphicsProbe.value(text, pidKey));
        return new JSONObject().put("role", child.role).put("pid", pid < 0 ? JSONObject.NULL : pid)
                .put("uid", uid < 0 ? JSONObject.NULL : uid).put("uidMatchesApp", uid == appUid)
                .put("exitCode", child.process.isAlive() ? JSONObject.NULL : child.process.exitValue())
                .put("running", child.process.isAlive());
    }

    private static int parseInt(String value) {
        try { return Integer.parseInt(value); }
        catch (NumberFormatException ignored) { return -1; }
    }

    private static long parseLong(String value) {
        try { return Long.parseLong(value); }
        catch (NumberFormatException ignored) { return -1; }
    }

    private static String read(File file) throws Exception {
        return file.isFile() ? new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8) : "";
    }

    private static String diagnosticTails(List<Child> children) {
        StringBuilder output = new StringBuilder();
        for (Child child : children) {
            try {
                String text = read(child.log);
                int start = Math.max(0, text.length() - 12000);
                output.append('[').append(child.role).append("]\n")
                        .append(text, start, text.length()).append('\n');
            } catch (Exception ignored) {
                output.append('[').append(child.role).append("] <log unavailable>\n");
            }
        }
        return output.toString();
    }

    private static boolean removeTree(File directory) {
        File[] children = directory.listFiles();
        if (children == null) return !directory.exists();
        boolean removed = true;
        for (File child : children) {
            if (child.isDirectory()) removed &= removeTree(child);
            else {
                try { Files.deleteIfExists(child.toPath()); }
                catch (Exception ignored) { removed = false; }
            }
        }
        try { Files.deleteIfExists(directory.toPath()); }
        catch (Exception ignored) { removed = false; }
        return removed && !directory.exists();
    }

    private static void require(boolean passed, String message) {
        if (!passed) throw new IllegalStateException(message);
    }

    private interface StatsPredicate { boolean matches(JSONArray stats) throws Exception; }

    private static final class Child {
        final String role;
        final Process process;
        final File log;

        Child(String role, Process process, File log) {
            this.role = role;
            this.process = process;
            this.log = log;
        }
    }
}
