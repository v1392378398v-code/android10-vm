package io.a10vm.containerprobe;

import android.content.Context;
import android.os.Process;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** The guest uses Android 10 Bionic; the host alone opens EGL/GLES. */
final class GraphicsProbe {
    private final Context context;

    GraphicsProbe(Context context) { this.context = context; }

    JSONObject run(String nonce) throws Exception {
        LoaderProbe runtime = new LoaderProbe(context);
        JSONObject inputs = runtime.readInputs("graphics-inputs.json");
        Set<String> allowed = runtime.verifyInputs(runtime.readInputs("inputs.json").getJSONArray("files"));
        runtime.verifyInputs(inputs.getJSONArray("files"));
        File client = runtime.nativeFile("liba10vm-p1-client.so");
        File host = runtime.nativeFile("liba10vm-p1-host.so");
        File linker = runtime.nativeFile("liba10vm-a10-linker.so");
        File libc = runtime.nativeFile("liba10vm-a10-libc.so");
        allowed.add(client.getCanonicalPath());
        File config = runtime.prepareRuntime("graphics", false);
        File directory = new File(context.getFilesDir(), "graphics-stage0");
        Files.createDirectories(directory.toPath());
        File socket = new File(directory, "gles.sock");
        Files.deleteIfExists(socket.toPath());
        File hostOutput = new File(directory, "host.log");
        JSONObject result = new JSONObject().put("gate", "P1a-android10-codec-pbuffer")
                .put("passed", false).put("surfaceVerified", false).put("desktopVerified", false)
                .put("privatePropertiesImplemented", false).put("inputs", inputs);
        JSONObject guest = new JSONObject();
        java.lang.Process server = null;
        boolean timedOut = false;
        long start = SystemClock.elapsedRealtime();
        try {
            server = ProbeProcess.builder(directory, hostOutput,
                    Arrays.asList(host.getCanonicalPath(), socket.getAbsolutePath(), nonce), null).start();
            awaitReady(server, hostOutput);
            guest = ProbeProcess.run(directory, "client",
                    Arrays.asList(linker.getCanonicalPath(), client.getCanonicalPath(),
                            socket.getAbsolutePath(), nonce), config);
            timedOut = !server.waitFor(8, TimeUnit.SECONDS);
        } catch (Exception error) {
            result.put("error", error.toString());
        } finally {
            if (server != null && server.isAlive()) {
                server.destroyForcibly();
                if (!server.waitFor(2, TimeUnit.SECONDS)) {
                    result.put("error", "Graphics host did not exit after termination");
                }
            }
            result.put("host", new JSONObject().put("output", read(hostOutput))
                    .put("elapsedMs", SystemClock.elapsedRealtime() - start)
                    .put("timedOut", timedOut).put("exitCode",
                            server == null || server.isAlive() ? -1 : server.exitValue()));
            result.put("guest", guest);
            Files.deleteIfExists(hostOutput.toPath());
            Files.deleteIfExists(socket.toPath());
        }
        JSONObject hostRun = result.getJSONObject("host");
        String guestText = guest.optString("output");
        String hostText = hostRun.getString("output");
        Set<String> mappings = LoaderProbe.executableMaps(guestText);
        boolean isolated = allowed.containsAll(mappings)
                && mappings.contains(client.getCanonicalPath()) && mappings.contains(linker.getCanonicalPath())
                && mappings.contains(libc.getCanonicalPath())
                && libc.getCanonicalPath().equals(new File(value(guestText, "libc")).getCanonicalPath());
        String codec = "codec=" + inputs.getString("codec");
        boolean passed = !result.has("error") && completed(guest, nonce) && completed(hostRun, nonce)
                && isolated && guestText.contains("CLIENT_OK frames=32 pixels=64 ")
                && hostText.contains("HOST_OK frames=32 ")
                && guestText.contains(codec) && hostText.contains(codec);
        return result.put("passed", passed).put("guestLibraryIsolationPassed", isolated)
                .put("guestExecutableMappings", new JSONArray(mappings));
    }

    private static void awaitReady(java.lang.Process server, File output) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        while (SystemClock.elapsedRealtime() < deadline) {
            String log = read(output);
            if (log.contains("\nHOST_READY\n")) return;
            if (!server.isAlive()) throw new IllegalStateException("Graphics host exited before ready: " + log);
            Thread.sleep(20);
        }
        throw new IllegalStateException("Graphics host readiness timeout");
    }

    private static boolean completed(JSONObject run, String nonce) {
        String text = run.optString("output");
        return !run.optBoolean("timedOut", true) && run.optInt("exitCode", -1) == 0
                && appIdentity(text, nonce);
    }

    static boolean appIdentity(String text, String nonce) {
        String uid = Integer.toString(Process.myUid());
        return Process.myUid() >= 10000 && nonce.equals(value(text, "nonce"))
                && uid.equals(value(text, "uid")) && uid.equals(value(text, "euid"))
                && "0000000000000000".equals(value(text, "cap_eff"))
                && value(text, "selinux").matches("u:r:untrusted_app(?:_[0-9]+)?:s0(?::.*)?");
    }

    static String value(String output, String key) {
        for (String line : output.split("\n")) {
            if (line.startsWith(key + "=")) return line.substring(key.length() + 1);
        }
        return "";
    }

    private static String read(File file) throws Exception {
        return file.isFile() ? new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8) : "";
    }
}
