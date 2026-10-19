package io.a10vm.containerprobe;

import android.content.Context;
import android.os.SystemClock;
import android.view.Surface;
import android.view.MotionEvent;
import io.a10vm.nativedisplay.WindowBridge;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** One guest lifetime; Activities only lend their current Surface. */
final class SurfaceProbeSession implements AutoCloseable {
    private static SurfaceProbeSession active;
    static synchronized SurfaceProbeSession acquire(Context context, String nonce) {
        if (active == null || active.closed) active = new SurfaceProbeSession(context, nonce);
        return active;
    }

    private final Context context;
    private final String nonce;
    private final File directory, output;
    private final ExecutorService startup = Executors.newSingleThreadExecutor();
    private final Set<String> allowed = new HashSet<>();
    private volatile Process guest;
    private volatile boolean closed;
    private volatile String failure = "";
    private volatile boolean forcedStop;
    private volatile boolean stopWriteSucceeded;
    private long handle, attachment, nativeGeneration;
    private Surface surface;
    private JSONObject inputs;

    private SurfaceProbeSession(Context context, String nonce) {
        this.context = context.getApplicationContext();
        this.nonce = nonce;
        directory = new File(context.getFilesDir(), "window-stage0");
        output = new File(directory, "guest.log");
        startup.execute(this::start);
    }

    private void start() {
        try {
            LoaderProbe runtime = new LoaderProbe(context);
            inputs = runtime.readInputs("graphics-inputs.json");
            allowed.addAll(runtime.verifyInputs(runtime.readInputs("inputs.json").getJSONArray("files")));
            runtime.verifyInputs(inputs.getJSONArray("files"));
            File client = runtime.nativeFile("liba10vm-p1-client.so");
            File linker = runtime.nativeFile("liba10vm-a10-linker.so");
            allowed.add(client.getCanonicalPath());
            File config = runtime.prepareRuntime("window", false);
            Files.createDirectories(directory.toPath());
            Files.deleteIfExists(new File(directory, "gles.sock").toPath());
            Files.deleteIfExists(new File(directory, "input.sock").toPath());
            synchronized (this) {
                if (closed) return;
                handle = WindowBridge.create(directory.getAbsolutePath());
                if (surface != null && surface.isValid()) nativeGeneration = WindowBridge.attach(handle, surface);
            }
            long deadline = SystemClock.elapsedRealtime() + 5000;
            while (snapshot().ready == 0) {
                if (closed) return;
                if (!error().isEmpty()) throw new IllegalStateException(error());
                if (SystemClock.elapsedRealtime() >= deadline) throw new IllegalStateException("Window renderer start timeout");
                Thread.sleep(10);
            }
            Process process = ProbeProcess.builder(directory, output, Arrays.asList(
                    linker.getCanonicalPath(), client.getCanonicalPath(), "--window",
                    new File(directory, "gles.sock").getAbsolutePath(),
                    new File(directory, "input.sock").getAbsolutePath(), nonce), config).start();
            guest = process;
            if (closed) {
                process.destroyForcibly();
            }
        } catch (Exception | LinkageError error) {
            failure = error.toString();
        }
    }

    synchronized long attach(Surface next) {
        surface = next;
        ++attachment;
        if (handle != 0) nativeGeneration = WindowBridge.attach(handle, next);
        return attachment;
    }

    synchronized void detach(long token) {
        if (token != attachment) return;
        surface = null;
        if (handle != 0) WindowBridge.detach(handle, nativeGeneration);
    }

    synchronized void tap(int x, int y) {
        if (handle != 0) WindowBridge.tap(handle, x, y);
    }

    synchronized void touch(MotionEvent event, int width, int height) {
        if (handle != 0) WindowBridge.submit(handle, event, width, height);
    }

    synchronized WindowSnapshot snapshot() {
        return new WindowSnapshot(handle == 0 ? new long[17] : WindowBridge.metrics(handle));
    }

    synchronized String error() {
        if (!failure.isEmpty()) return failure;
        String renderer = handle == 0 ? "" : WindowBridge.error(handle);
        if (!renderer.isEmpty()) return renderer;
        if (!closed && guest != null && !guest.isAlive()) return "Window guest exited: " + guest.exitValue();
        return "";
    }

    synchronized String description() { return handle == 0 ? "" : WindowBridge.description(handle); }
    synchronized long[] intervals() { return handle == 0 ? new long[0] : WindowBridge.intervals(handle); }
    synchronized void resetTimings() { if (handle != 0) WindowBridge.resetTimings(handle); }

    synchronized JSONObject guestEvidence() throws Exception {
        String text = output.isFile() ? new String(Files.readAllBytes(output.toPath()), StandardCharsets.UTF_8) : "";
        Set<String> maps = LoaderProbe.executableMaps(text);
        LoaderProbe runtime = new LoaderProbe(context);
        boolean isolated = maps.size() == 5 && allowed.containsAll(maps)
                && maps.contains(runtime.nativeFile("liba10vm-p1-client.so").getCanonicalPath())
                && maps.contains(runtime.nativeFile("liba10vm-a10-linker.so").getCanonicalPath())
                && runtime.nativeFile("liba10vm-a10-libc.so").getCanonicalPath().equals(GraphicsProbe.value(text, "libc"));
        return new JSONObject().put("identityPassed", GraphicsProbe.appIdentity(text, nonce))
                .put("libraryIsolationPassed", isolated).put("mappings", new JSONArray(maps))
                .put("pid", GraphicsProbe.value(text, "pid")).put("output", text)
                .put("alive", guest != null && guest.isAlive()).put("inputs", inputs);
    }

    @Override public void close() {
        synchronized (this) {
            if (closed) return;
            closed = true;
            if (handle != 0) stopWriteSucceeded = WindowBridge.requestExit(handle);
        }
        startup.shutdown();
        try {
            boolean startupStopped = startup.awaitTermination(7, TimeUnit.SECONDS);
            if (!startupStopped) failure = "Window startup did not stop";
            boolean guestStopped = guest == null || guest.waitFor(2, TimeUnit.SECONDS);
            if (!guestStopped) {
                forcedStop = true;
                guest.destroyForcibly();
                if (!guest.waitFor(2, TimeUnit.SECONDS)) failure = "Window guest did not stop";
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); failure = error.toString();
            if (guest != null && guest.isAlive()) guest.destroyForcibly();
        } finally {
            long previous;
            synchronized (this) { previous = handle; handle = 0; surface = null; }
            if (previous != 0) WindowBridge.destroy(previous);
        }
    }

    JSONObject cleanupEvidence() throws Exception {
        return new JSONObject().put("forcedStop", forcedStop).put("stopWriteSucceeded", stopWriteSucceeded)
                .put("error", failure)
                .put("guestAlive", guest != null && guest.isAlive())
                .put("guestExit", guest == null || guest.isAlive() ? -1 : guest.exitValue());
    }
}
