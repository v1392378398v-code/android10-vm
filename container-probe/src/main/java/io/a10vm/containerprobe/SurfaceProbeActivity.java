package io.a10vm.containerprobe;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.util.UUID;

public final class SurfaceProbeActivity extends Activity implements SurfaceHolder.Callback {
    static volatile SurfaceProbeActivity current;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private SurfaceProbeSession session;
    private SurfaceView surface;
    private TextView status;
    private long attachment;
    private final Runnable monitor = new Runnable() {
        @Override public void run() {
            String error = session.error();
            status.setText(error.isEmpty() ? "Android 10 图形探针启动中" : error);
            status.setVisibility(error.isEmpty() && session.snapshot().swaps > 0 ? View.GONE : View.VISIBLE);
            handler.postDelayed(this, 250);
        }
    };

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setDecorFitsSystemWindows(false);
        String nonce = getIntent().getStringExtra("nonce");
        session = SurfaceProbeSession.acquire(this, nonce == null ? UUID.randomUUID().toString() : nonce);
        FrameLayout layout = new FrameLayout(this);
        surface = new SurfaceView(this);
        surface.getHolder().setFixedSize(360, 640);
        surface.getHolder().addCallback(this);
        surface.setOnTouchListener((view, event) -> {
            session.touch(event, view.getWidth(), view.getHeight());
            if (event.getActionMasked() == MotionEvent.ACTION_UP) view.performClick();
            return true;
        });
        layout.addView(surface, new FrameLayout.LayoutParams(-1, -1));
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setGravity(Gravity.CENTER);
        status.setBackgroundColor(0xcc111111);
        layout.addView(status, new FrameLayout.LayoutParams(-1, -1));
        setContentView(layout);
        hideSystemBars();
        handler.post(monitor);
    }

    private void hideSystemBars() {
        WindowInsetsController insets = getWindow().getDecorView().getWindowInsetsController();
        if (insets != null) {
            insets.hide(WindowInsets.Type.systemBars());
            insets.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
        }
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) hideSystemBars();
    }

    @Override protected void onResume() {
        super.onResume(); current = this;
    }
    @Override protected void onPause() {
        if (current == this) current = null;
        super.onPause();
    }
    @Override protected void onDestroy() {
        handler.removeCallbacks(monitor);
        if (attachment != 0) session.detach(attachment);
        super.onDestroy();
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        attachment = session.attach(holder.getSurface());
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        session.detach(attachment);
    }
    SurfaceProbeSession session() { return session; }
    SurfaceView surface() { return surface; }
}
