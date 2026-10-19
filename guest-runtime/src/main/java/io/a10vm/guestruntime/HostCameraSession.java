package io.a10vm.guestruntime;

import android.graphics.ImageFormat;
import android.hardware.Camera;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** One host camera, its callback thread and a bounded queue of guest events. */
@SuppressWarnings("deprecation")
final class HostCameraSession implements AutoCloseable {
    private final HandlerThread thread = new HandlerThread("host-camera");
    private final Handler handler;
    private final ArrayDeque<Event> events = new ArrayDeque<>();
    private Camera camera;
    private HostCameraPreview preview;
    private volatile boolean closed;
    private boolean previewing;

    private static final class Event {
        final int type, value;
        final long timestamp = SystemClock.elapsedRealtimeNanos();
        final byte[] bytes;
        Event(int type, int value, byte[] bytes) {
            this.type = type; this.value = value; this.bytes = bytes;
        }
    }

    HostCameraSession(int id) throws Exception {
        thread.start();
        handler = new Handler(thread.getLooper());
        try {
            call(() -> {
                camera = Camera.open(id);
                Camera.Parameters parameters = camera.getParameters();
                List<Camera.Size> sizes = parameters.getSupportedPreviewSizes();
                Camera.Size choice = sizes.get(0);
                for (Camera.Size size : sizes) {
                    if (size.width == 640 && size.height == 480) { choice = size; break; }
                }
                parameters.setPreviewSize(choice.width, choice.height);
                parameters.setPreviewFormat(ImageFormat.NV21);
                camera.setParameters(parameters);
                preview = new HostCameraPreview(handler);
                camera.setPreviewTexture(preview.texture);
                camera.setErrorCallback((error, source) -> enqueue(new Event(5, error, null)));
                return null;
            });
        } catch (Exception error) { close(); throw error; }
    }

    private <T> T call(Callable<T> work) throws Exception {
        FutureTask<T> task = new FutureTask<>(work);
        if (!handler.post(task)) throw new IOException("Camera thread stopped");
        return task.get(5, TimeUnit.SECONDS);
    }

    private String visibleParameters() {
        Camera.Parameters parameters = camera.getParameters();
        // Face metadata is absent from this transport; the LEGACY mapper reads these capabilities.
        parameters.set("max-num-detected-faces-hw", 0);
        parameters.set("max-num-detected-faces-sw", 0);
        return parameters.flatten();
    }

    String parameters() throws Exception { return call(this::visibleParameters); }

    String command(int command, String parameters, int value) throws Exception {
        return call(() -> {
            if (closed) throw new IOException("Camera closed");
            switch (command) {
                case 1: return visibleParameters();
                case 2:
                    boolean resume = previewing;
                    if (resume) stopPreview();
                    Camera.Parameters actual = camera.getParameters();
                    Camera.Parameters updated = camera.getParameters();
                    updated.unflatten(parameters);
                    for (String key : new String[] {"max-num-detected-faces-hw", "max-num-detected-faces-sw"}) {
                        String capability = actual.get(key);
                        if (capability == null) updated.remove(key);
                        else updated.set(key, capability);
                    }
                    updated.setPreviewFormat(ImageFormat.NV21);
                    camera.setParameters(updated);
                    if (resume) startPreview();
                    return visibleParameters();
                case 3: startPreview(); break;
                case 4: stopPreview(); break;
                case 5: camera.autoFocus((success, source) -> enqueue(new Event(4, success ? 1 : 0, null))); break;
                case 6: camera.cancelAutoFocus(); break;
                case 7:
                    camera.takePicture(() -> enqueue(new Event(2, 0, null)), null,
                            (bytes, source) -> enqueue(new Event(3, 0, bytes)));
                    previewing = false;
                    break;
                case 8: camera.setDisplayOrientation(value); break;
                case 10:
                    camera.setAutoFocusMoveCallback(value == 0 ? null :
                            (moving, source) -> enqueue(new Event(6, moving ? 1 : 0, null)));
                    break;
                default: throw new IOException("Camera command");
            }
            return "";
        });
    }

    private void startPreview() {
        if (previewing) return;
        Camera.Size size = camera.getParameters().getPreviewSize();
        int bytes = size.width * size.height * 3 / 2;
        camera.setPreviewCallbackWithBuffer((data, source) -> {
            if (!closed && data != null) {
                enqueue(new Event(1, 0, data.clone()));
                source.addCallbackBuffer(data);
            }
        });
        for (int i = 0; i < 3; ++i) camera.addCallbackBuffer(new byte[bytes]);
        camera.startPreview();
        previewing = true;
    }

    private void stopPreview() {
        camera.setPreviewCallbackWithBuffer(null);
        camera.stopPreview();
        previewing = false;
        synchronized (this) { events.removeIf(event -> event.type == 1); }
    }

    private synchronized void enqueue(Event event) {
        if (closed) return;
        if (event.type == 1) events.removeIf(pending -> pending.type == 1);
        if (events.size() >= 8) events.removeFirst();
        events.addLast(event);
        notifyAll();
    }

    void stream(DataOutputStream output) throws Exception {
        while (true) {
            Event event;
            synchronized (this) {
                while (events.isEmpty() && !closed) wait();
                if (closed) return;
                event = events.removeFirst();
            }
            output.writeInt(event.type); output.writeInt(event.value); output.writeLong(event.timestamp);
            output.writeInt(event.bytes == null ? 0 : event.bytes.length);
            if (event.bytes != null) output.write(event.bytes);
            output.flush();
        }
    }

    @Override public void close() {
        synchronized (this) {
            if (closed) return;
            closed = true; events.clear(); notifyAll();
        }
        try {
            call(() -> {
                if (camera != null) { camera.release(); camera = null; }
                if (preview != null) { preview.close(); preview = null; }
                return null;
            });
        } catch (Exception error) { android.util.Log.w("A10VM", "Host camera release", error); }
        finally { thread.quitSafely(); }
    }
}
