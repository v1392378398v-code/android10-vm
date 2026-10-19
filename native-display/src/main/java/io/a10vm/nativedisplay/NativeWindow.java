package io.a10vm.nativedisplay;

import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.Surface;
import java.io.File;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.function.LongFunction;

/** Service-owned GPU endpoint; a Surface attachment does not own the guest. */
public final class NativeWindow implements AutoCloseable {
    private long handle;
    private final ReentrantReadWriteLock lifetime = new ReentrantReadWriteLock();
    public NativeWindow(File directory) { handle = WindowBridge.create(directory.getAbsolutePath()); }
    private <T> T access(LongFunction<T> operation, T absent) {
        lifetime.readLock().lock();
        try { return handle == 0 ? absent : operation.apply(handle); }
        finally { lifetime.readLock().unlock(); }
    }
    public long attach(Surface surface) { return access(value -> WindowBridge.attach(value, surface), 0L); }
    public void detach(long generation) {
        access(value -> { WindowBridge.detach(value, generation); return null; }, null);
    }
    public void touch(MotionEvent event, int width, int height) {
        // Input is best-effort: a saturated or torn-down channel must not fault the UI thread.
        try {
            access(value -> WindowBridge.submit(value, event, width, height), 0);
        } catch (IllegalStateException | UnsatisfiedLinkError ignored) {
        }
    }
    public void cancelTouch() {
        access(value -> WindowBridge.touch(value, MotionEvent.ACTION_CANCEL, 0,
                SystemClock.uptimeMillis() * 1000000, new int[0], new int[0], new int[0], new float[0]), 0);
    }
    public long[] metrics() { return access(WindowBridge::metrics, new long[17]); }
    public String error() { return access(WindowBridge::error, ""); }
    public String description() { return access(WindowBridge::description, ""); }
    public boolean requestExit() { return access(WindowBridge::requestExit, false); }
    @Override public void close() {
        long previous;
        lifetime.writeLock().lock();
        try { previous = handle; handle = 0; }
        finally { lifetime.writeLock().unlock(); }
        if (previous == 0) return;
        WindowBridge.destroy(previous);
    }
}
