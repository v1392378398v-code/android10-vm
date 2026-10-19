package io.a10vm.nativedisplay;

import android.content.Context;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

public final class NativeSurfaceView extends SurfaceView implements SurfaceHolder.Callback {
    private NativeWindow window;
    private long attachment;
    private boolean touching;
    public NativeSurfaceView(Context context) {
        super(context);
        getHolder().setFixedSize(WindowBridge.WIDTH, WindowBridge.HEIGHT);
        getHolder().addCallback(this);
    }
    public void connect(NativeWindow next) {
        if (window == next) return;
        detach();
        window = next;
        attach();
    }
    private void attach() {
        if (window != null && getHolder().getSurface().isValid() && attachment == 0)
            attachment = window.attach(getHolder().getSurface());
    }
    private void detach() {
        if (window != null) {
            if (touching) window.cancelTouch();
            if (attachment != 0) window.detach(attachment);
        }
        touching = false; attachment = 0;
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        if (android.os.Build.VERSION.SDK_INT >= 30) holder.getSurface().setFrameRate(WindowBridge.REFRESH_HZ,
                android.view.Surface.FRAME_RATE_COMPATIBILITY_DEFAULT);
        attach();
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { attach(); }
    @Override public void surfaceDestroyed(SurfaceHolder holder) { detach(); }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (window == null || attachment == 0) return false;
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) touching = true;
        if (!touching) return false;
        window.touch(event, getWidth(), getHeight());
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) touching = false;
        if (action == MotionEvent.ACTION_UP) performClick();
        return true;
    }
    @Override public boolean performClick() { super.performClick(); return true; }
    @Override protected void onMeasure(int widthSpec, int heightSpec) {
        int width = MeasureSpec.getSize(widthSpec), height = MeasureSpec.getSize(heightSpec);
        if ((long)width * WindowBridge.HEIGHT > (long)height * WindowBridge.WIDTH)
            width = height * WindowBridge.WIDTH / WindowBridge.HEIGHT;
        else height = width * WindowBridge.HEIGHT / WindowBridge.WIDTH;
        setMeasuredDimension(width, height);
    }
}
