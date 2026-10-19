package io.a10vm.containerprobe;

import android.app.Instrumentation;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.view.PixelCopy;
import android.view.SurfaceView;
import org.json.JSONObject;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.IntBinaryOperator;

/** PixelCopy measures a submitted Surface buffer; screenshots additionally sample composition. */
final class WindowPixels {
    final int frame, input;
    final boolean marker;
    final long completedNanos, captureNanos;

    private WindowPixels(IntBinaryOperator pixel, int x, int y, long start) {
        frame = bits(pixel, 28);
        input = bits(pixel, 68);
        int color = pixel.applyAsInt(x, y);
        marker = Color.red(color) > 220 && Color.green(color) < 35 && Color.blue(color) > 220;
        completedNanos = System.nanoTime();
        captureNanos = completedNanos - start;
    }

    private static int bits(IntBinaryOperator pixel, int y) {
        int value = 0;
        for (int bit = 0; bit < 16; ++bit) {
            int color = pixel.applyAsInt(16 + 21 * bit, y);
            boolean white = Color.red(color) > 220 && Color.green(color) > 220 && Color.blue(color) > 220;
            boolean black = Color.red(color) < 35 && Color.green(color) < 35 && Color.blue(color) < 35;
            if (!white && !black) throw new IllegalStateException("Missing guest sequence pixels");
            if (white) value |= 1 << bit;
        }
        return value;
    }

    static WindowPixels surface(SurfaceView view, int x, int y) throws Exception {
        long start = System.nanoTime();
        Bitmap bitmap = Bitmap.createBitmap(360, 640, Bitmap.Config.ARGB_8888);
        CountDownLatch done = new CountDownLatch(1);
        int[] status = {-1};
        try {
            PixelCopy.request(view, bitmap, result -> { status[0] = result; done.countDown(); },
                    new Handler(Looper.getMainLooper()));
            if (!done.await(2, TimeUnit.SECONDS) || status[0] != PixelCopy.SUCCESS) {
                throw new IllegalStateException("Surface sample failed: " + status[0]);
            }
            return new WindowPixels(bitmap::getPixel, x, y, start);
        } finally {
            // After timeout a pending PixelCopy may still own this bitmap.
            if (done.getCount() == 0) bitmap.recycle();
        }
    }

    static WindowPixels screen(Instrumentation instrumentation, SurfaceView view, int x, int y) {
        long start = System.nanoTime();
        int[] bounds = bounds(instrumentation, view);
        Bitmap raw = instrumentation.getUiAutomation().takeScreenshot();
        if (raw == null) throw new IllegalStateException("Compositor screenshot missing");
        Bitmap bitmap = raw.getConfig() == Bitmap.Config.HARDWARE ? raw.copy(Bitmap.Config.ARGB_8888, false) : raw;
        try {
            return new WindowPixels((px, py) -> bitmap.getPixel(bounds[0] + px * bounds[2] / 360,
                    bounds[1] + py * bounds[3] / 640), x, y, start);
        } finally {
            bitmap.recycle();
            if (raw != bitmap) raw.recycle();
        }
    }

    static int[] bounds(Instrumentation instrumentation, SurfaceView view) {
        int[] result = new int[4];
        instrumentation.runOnMainSync(() -> {
            if (!view.isShown() || !view.hasWindowFocus()) return;
            int[] location = new int[2];
            view.getLocationOnScreen(location);
            result[0] = location[0]; result[1] = location[1];
            result[2] = view.getWidth(); result[3] = view.getHeight();
        });
        if (result[2] == 0 || result[3] == 0) throw new IllegalStateException("Probe window is not foreground");
        return result;
    }

    JSONObject json() throws Exception {
        return new JSONObject().put("frame", frame).put("input", input).put("marker", marker)
                .put("completedNanos", completedNanos).put("captureMs", captureNanos / 1e6);
    }
}
