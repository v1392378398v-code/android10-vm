package io.a10vm.fixture.webview;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public final class ViewportActivity extends Activity {
    private WebView web;
    private boolean drawHardware;

    final class Report {
        @JavascriptInterface public void save(String data) {
            runOnUiThread(() -> {
                try {
                    JSONObject report = new JSONObject(data);
                    report.put("fixtureId", getIntent().getStringExtra("fixtureId"));
                    DisplayMetrics metrics = getResources().getDisplayMetrics();
                    int[] position = new int[2];
                    web.getLocationOnScreen(position);
                    report.put("native", new JSONObject().put("width", web.getWidth())
                            .put("height", web.getHeight()).put("x", position[0]).put("y", position[1])
                            .put("density", metrics.density).put("densityDpi", metrics.densityDpi)
                            .put("screenWidth", metrics.widthPixels).put("screenHeight", metrics.heightPixels)
                            .put("hardwareAccelerated", web.isHardwareAccelerated())
                            .put("drawHardware", drawHardware).put("layerType", web.getLayerType()));
                    try (FileOutputStream output = new FileOutputStream(new File(getFilesDir(), "viewport.json"))) {
                        output.write(report.toString().getBytes(StandardCharsets.UTF_8));
                    }
                    if (!getIntent().getBooleanExtra("playback", false))
                        android.util.Log.i("A10VM-Viewport", report.toString());
                } catch (Exception failure) { throw new IllegalStateException("Viewport report", failure); }
            });
        }
    }

    private final class Reference extends android.view.View {
        private final Paint paint = new Paint();
        Reference() { super(ViewportActivity.this); }
        @Override protected void onDraw(Canvas canvas) {
            int side = Math.round(40 * getResources().getDisplayMetrics().density);
            canvas.drawColor(Color.WHITE);
            paint.setColor(Color.rgb(0, 180, 80));
            canvas.drawRect(0, 0, side, side, paint);
            paint.setColor(Color.rgb(230, 0, 200));
            canvas.drawCircle(side * 1.5f, side * .5f, side * .5f, paint);
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int height = Math.round(40 * getResources().getDisplayMetrics().density);
        layout.addView(new Reference(), new LinearLayout.LayoutParams(-1, height));
        WebView.setWebContentsDebuggingEnabled(true);
        web = new WebView(this) {
            @Override protected void onDraw(Canvas canvas) {
                drawHardware = canvas.isHardwareAccelerated();
                super.onDraw(canvas);
            }
        };
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setUseWideViewPort(true);
        web.getSettings().setLoadWithOverviewMode(true);
        web.getSettings().setMediaPlaybackRequiresUserGesture(false);
        web.setWebChromeClient(new WebChromeClient());
        String url = getIntent().getStringExtra("url");
        if (url == null) {
            web.addJavascriptInterface(new Report(), "ViewportReport");
            url = getIntent().getBooleanExtra("playback", false)
                    ? "file:///android_asset/playback.html?muted=" + getIntent().getBooleanExtra("muted", false)
                    : "file:///android_asset/viewport.html";
        }
        web.setWebViewClient(new WebViewClient());
        if (getIntent().getBooleanExtra("software", false))
            web.setLayerType(android.view.View.LAYER_TYPE_SOFTWARE, null);
        layout.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        web.loadUrl(url);
    }
}
