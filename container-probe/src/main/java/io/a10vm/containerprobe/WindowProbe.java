package io.a10vm.containerprobe;

import android.app.Instrumentation;
import android.content.Intent;
import android.os.Process;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;

final class WindowProbe {
    private final Instrumentation instrumentation;
    private SurfaceProbeSession session;

    WindowProbe(Instrumentation instrumentation) { this.instrumentation = instrumentation; }

    JSONObject run(String nonce, int durationMs, int touches) throws Exception {
        JSONObject result = new JSONObject().put("gate", "P1b-android10-gles-window")
                .put("passed", false).put("desktopVerified", false).put("physicalDisplayLatencyMeasured", false);
        boolean functional = false;
        try {
            long start = System.nanoTime();
            SurfaceProbeActivity activity = (SurfaceProbeActivity) instrumentation.startActivitySync(
                    new Intent(instrumentation.getTargetContext(), SurfaceProbeActivity.class)
                            .putExtra("nonce", nonce).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            session = activity.session();
            awaitWindow(null, 0);
            WindowPixels first = awaitPixels(false, 0, 180, 320);
            result.put("firstSurfaceSampleMs", (first.completedNanos - start) / 1e6);
            result.put("firstComposedSample", awaitPixels(true, 0, 180, 320).json());
            JSONObject guest = session.guestEvidence();
            require(guest.getBoolean("identityPassed") && guest.getBoolean("libraryIsolationPassed"), "Guest identity/libraries");
            String pid = guest.getString("pid");
            result.put("guestBefore", guest).put("gpu", session.description());
            result.put("measurement", measure(durationMs, touches));
            JSONArray rebuilds = new JSONArray();
            for (int i = 0; i < 10; ++i) {
                SurfaceProbeActivity old = SurfaceProbeActivity.current;
                long generation = session.snapshot().requestedGeneration;
                long before = System.nanoTime();
                instrumentation.runOnMainSync(old::recreate);
                awaitWindow(old, generation);
                WindowPixels pixels = awaitPixels(true, touches * 2, lastX(touches - 1), lastY(touches - 1));
                JSONObject identity = session.guestEvidence();
                require(identity.getBoolean("alive") && pid.equals(identity.getString("pid")), "Guest restarted with window");
                rebuilds.put(new JSONObject().put("index", i + 1).put("pid", pid)
                        .put("generation", session.snapshot().presentedGeneration)
                        .put("restoreToComposedSampleMs", (pixels.completedNanos - before) / 1e6)
                        .put("pixels", pixels.json()));
            }
            WindowSnapshot state = session.snapshot();
            result.put("rebuilds", rebuilds).put("final", state.json());
            String status = new String(Files.readAllBytes(Paths.get("/proc/self/status")), StandardCharsets.UTF_8);
            String selinux = new String(Files.readAllBytes(Paths.get("/proc/self/attr/current")), StandardCharsets.UTF_8)
                    .replace("\u0000", "").trim();
            require(state.uid == Process.myUid() && state.euid == Process.myUid()
                    && status.matches("(?s).*CapEff:\\s+0000000000000000\\s.*")
                    && selinux.matches("u:r:untrusted_app(?:_[0-9]+)?:s0(?::.*)?"), "Host identity");
            result.put("hostSelinux", selinux).put("hostCapabilities", "0000000000000000");
            functional = true;
        } catch (Exception error) {
            result.put("error", error.toString());
            if (session != null) result.put("nativeError", session.error()).put("atFailure", session.snapshot().json());
        } finally {
            if (session != null) {
                session.close();
                JSONObject cleanup = session.cleanupEvidence();
                JSONObject last = session.guestEvidence();
                result.put("cleanup", cleanup).put("guestAfter", last);
                String output = last.getString("output");
                functional &= cleanup.getBoolean("stopWriteSucceeded")
                        && !cleanup.getBoolean("forcedStop") && !cleanup.getBoolean("guestAlive")
                        && cleanup.getInt("guestExit") == 0 && cleanup.getString("error").isEmpty()
                        && last.getBoolean("identityPassed") && last.getBoolean("libraryIsolationPassed")
                        && output.contains("CLIENT_WINDOW_STOP_RECEIVED sequence=")
                        && output.contains("CLIENT_WINDOW_DONE frames=")
                        && output.contains("identity_stage=exit\n");
            }
            SurfaceProbeActivity current = SurfaceProbeActivity.current;
            if (current != null) {
                instrumentation.runOnMainSync(current::finish);
            }
        }
        return result.put("passed", functional);
    }

    private JSONObject measure(int durationMs, int touches) throws Exception {
        require(durationMs >= 1000 && durationMs <= 90000 && touches > 0 && touches <= 150, "Measurement bounds");
        session.resetTimings();
        long start = System.nanoTime(), beforeFrames = session.snapshot().frames;
        double[] latencies = new double[touches];
        JSONArray samples = new JSONArray();
        for (int i = 0; i < touches; ++i) {
            sleepUntil(start + (long) i * durationMs * 1_000_000 / touches);
            int x = lastX(i), y = lastY(i);
            long event = System.nanoTime();
            injectTap(x, y);
            int sequence = (i + 1) * 2;
            WindowPixels pixels = awaitPixels(false, sequence, x, y);
            WindowSnapshot state = session.snapshot();
            require(state.inputSequence == sequence && state.echoSequence == sequence, "Touch sequence did not reach guest");
            latencies[i] = (pixels.completedNanos - event) / 1e6;
            samples.put(new JSONObject().put("input", i + 1).put("sample", pixels.json())
                    .put("injectionToSurfaceSampleMs", latencies[i])
                    .put("nativeInputToSwapReturnMs", (state.inputSubmitNanos - state.inputNanos) / 1e6));
        }
        sleepUntil(start + durationMs * 1_000_000L);
        long[] intervals = session.intervals();
        double[] gaps = new double[intervals.length];
        for (int i = 0; i < gaps.length; ++i) gaps[i] = intervals[i] / 1e6;
        long frames = session.snapshot().frames - beforeFrames;
        require(frames >= durationMs / 50 && gaps.length >= durationMs / 60, "Window frame progression is too slow");
        double frameP95 = percentile(gaps), inputP95 = percentile(latencies);
        return new JSONObject().put("durationMs", (System.nanoTime() - start) / 1e6)
                .put("requestedDurationMs", durationMs).put("resolution", new JSONArray(new int[]{360, 640}))
                .put("targetHz", 60).put("frames", frames).put("frameIntervalCount", intervals.length)
                .put("frameIntervalP95Ms", frameP95).put("injectionToSurfaceSampleP95Ms", inputP95)
                .put("probeBudgetPassed", frameP95 <= 50 && inputP95 <= 150)
                .put("fullDurationAndInputCount", durationMs >= 60000 && touches >= 100)
                .put("samples", samples);
    }

    private void injectTap(int x, int y) {
        int[] bounds = WindowPixels.bounds(instrumentation, SurfaceProbeActivity.current.surface());
        float sx = bounds[0] + x * bounds[2] / 360f, sy = bounds[1] + y * bounds[3] / 640f;
        long down = SystemClock.uptimeMillis();
        for (int action : new int[]{MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP}) {
            MotionEvent event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action, sx, sy, 0);
            event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
            try { instrumentation.sendPointerSync(event); } finally { event.recycle(); }
        }
    }

    private void awaitWindow(SurfaceProbeActivity previous, long generation) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 8000;
        while (SystemClock.elapsedRealtime() < deadline) {
            checkError();
            SurfaceProbeActivity current = SurfaceProbeActivity.current;
            WindowSnapshot state = session.snapshot();
            if (current != null && current != previous && state.presentedGeneration > generation && state.swaps > 2) return;
            Thread.sleep(10);
        }
        throw new IllegalStateException("Foreground Surface restoration timeout");
    }

    private WindowPixels awaitPixels(boolean screen, int input, int x, int y) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 3000;
        String last = "no sample";
        while (SystemClock.elapsedRealtime() < deadline) {
            checkError();
            try {
                SurfaceProbeActivity current = SurfaceProbeActivity.current;
                require(current != null, "Activity not resumed");
                WindowPixels pixels = screen ? WindowPixels.screen(instrumentation, current.surface(), x, y)
                        : WindowPixels.surface(current.surface(), x, y);
                if (pixels.frame > 0 && pixels.input == (input & 0xffff) && pixels.marker) return pixels;
                last = "frame=" + pixels.frame + " input=" + pixels.input + " marker=" + pixels.marker;
            } catch (IllegalStateException error) { last = error.toString(); }
            Thread.sleep(5);
        }
        throw new IllegalStateException("Guest pixels timeout: " + last);
    }

    private void checkError() { require(session.error().isEmpty(), session.error()); }
    private void sleepUntil(long nanos) throws Exception {
        while (System.nanoTime() < nanos) {
            checkError();
            Thread.sleep(Math.max(1, Math.min(100, (nanos - System.nanoTime()) / 1_000_000)));
        }
    }
    private static int lastX(int index) { return 60 + (index * 73) % 240; }
    private static int lastY(int index) { return 140 + (index * 97) % 420; }
    private static double percentile(double[] values) {
        require(values.length > 0, "Empty timing samples");
        double[] sorted = values.clone(); Arrays.sort(sorted);
        return sorted[(int)Math.ceil(sorted.length * .95) - 1];
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }
}
