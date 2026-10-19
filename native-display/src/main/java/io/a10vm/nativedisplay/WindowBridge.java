package io.a10vm.nativedisplay;

import android.view.MotionEvent;
import android.view.Surface;

public final class WindowBridge {
    static { System.loadLibrary("a10vm-desktop-window"); }
    private static native int[] displayMode();
    private static final int[] MODE = displayMode();
    public static final int WIDTH = MODE[0], HEIGHT = MODE[1], REFRESH_HZ = MODE[2], DENSITY = MODE[3];
    private WindowBridge() {}
    public static native long create(String directory);
    public static native long attach(long handle, Surface surface);
    public static native void detach(long handle, long generation);
    public static native int tap(long handle, int x, int y);
    public static native int touch(long handle, int action, int index, long timeNanos,
                                   int[] ids, int[] xs, int[] ys, float[] pressures);
    public static native long[] metrics(long handle);
    public static native long[] intervals(long handle);
    public static native String error(long handle);
    public static native String description(long handle);
    public static native void resetTimings(long handle);
    public static native boolean requestExit(long handle);
    public static native void destroy(long handle);

    public static int submit(long handle, MotionEvent event, int viewWidth, int viewHeight) {
        int action = event.getActionMasked();
        if (action != MotionEvent.ACTION_DOWN && action != MotionEvent.ACTION_UP &&
                action != MotionEvent.ACTION_MOVE && action != MotionEvent.ACTION_CANCEL &&
                action != MotionEvent.ACTION_POINTER_DOWN && action != MotionEvent.ACTION_POINTER_UP) return 0;
        int count = action == MotionEvent.ACTION_CANCEL ? 0 : event.getPointerCount();
        int[] ids = new int[count], xs = new int[count], ys = new int[count];
        float[] pressures = new float[count];
        for (int i = 0; i < count; ++i) ids[i] = event.getPointerId(i);
        // Only the current position is forwarded. Replaying batched history samples multiplied
        // every drag into N+1 synchronous round trips and is collapsed host-side instead.
        for (int i = 0; i < count; ++i) {
            xs[i] = scale(event.getX(i), viewWidth, WIDTH);
            ys[i] = scale(event.getY(i), viewHeight, HEIGHT);
            pressures[i] = event.getPressure(i);
        }
        return touch(handle, action, count == 0 ? 0 : event.getActionIndex(),
                event.getEventTime() * 1000000, ids, xs, ys, pressures);
    }

    private static int scale(float value, int extent, int target) {
        return Math.max(0, Math.min(target - 1, (int)(value * target / Math.max(1, extent))));
    }
}
