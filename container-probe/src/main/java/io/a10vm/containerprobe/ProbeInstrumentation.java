package io.a10vm.containerprobe;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;

public final class ProbeInstrumentation extends Instrumentation {
    private String nonce = UUID.randomUUID().toString();
    private boolean graphics;
    private boolean surface;
    private boolean properties;
    private boolean bootstrap;
    private boolean dynamic;
    private boolean companion;
    private boolean filesystem;
    private boolean binder;
    private int durationMs = 60000;
    private int touches = 100;

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments != null) {
            nonce = arguments.getString("nonce", nonce);
            surface = "true".equals(arguments.getString("surface"));
            graphics = surface || "true".equals(arguments.getString("graphics"));
            companion = "true".equals(arguments.getString("companion"));
            binder = "true".equals(arguments.getString("binder"));
            filesystem = "true".equals(arguments.getString("filesystem"));
            dynamic = companion || filesystem || "true".equals(arguments.getString("dynamic"));
            bootstrap = dynamic || "true".equals(arguments.getString("bootstrap"));
            properties = bootstrap || "true".equals(arguments.getString("properties"));
            durationMs = Integer.parseInt(arguments.getString("windowDurationMs", "60000"));
            touches = Integer.parseInt(arguments.getString("windowTouches", "100"));
        }
        start();
    }

    @Override public void onStart() {
        JSONObject report;
        try {
            report = new LoaderProbe(getTargetContext()).run(nonce);
            if (properties) {
                JSONObject property = new PropertyProbe(getTargetContext()).run(nonce, bootstrap, dynamic, companion, filesystem);
                report.put("properties", property).put("passed",
                        report.getBoolean("passed") && property.getBoolean("passed"));
            }
            if (graphics) {
                JSONObject rendering = new GraphicsProbe(getTargetContext()).run(nonce);
                report.put("graphics", rendering).put("passed",
                        report.getBoolean("passed") && rendering.getBoolean("passed"));
            }
            if (surface) {
                JSONObject window = new WindowProbe(this).run(nonce, durationMs, touches);
                report.put("window", window).put("passed",
                        report.getBoolean("passed") && window.getBoolean("passed"));
            }
            if (binder) {
                JSONObject binderResult = new BinderRuntimeProbe(getTargetContext()).run(nonce);
                JSONObject hwbinderResult = new HwBinderRuntimeProbe(getTargetContext()).run(nonce);
                report.put("binder", binderResult).put("hwbinder", hwbinderResult).put("passed",
                        report.getBoolean("passed") && binderResult.getBoolean("passed")
                                && hwbinderResult.getBoolean("passed"));
            }
        } catch (Exception error) {
            report = new JSONObject();
            try {
                report.put("passed", false).put("nonce", nonce).put("error", error.toString());
            } catch (org.json.JSONException ignored) { /* Fixed, non-null keys. */ }
        }
        Bundle result = new Bundle();
        try {
            File destination = new File(getTargetContext().getFilesDir(), "g1-stage0-report.json");
            Files.write(destination.toPath(), report.toString(2).getBytes(StandardCharsets.UTF_8));
            result.putString("report", destination.getAbsolutePath());
            result.putString("stream", "\nG1 stage-0 passed=" + report.optBoolean("passed") + "\n");
            finish(report.optBoolean("passed") ? Activity.RESULT_OK : Activity.RESULT_CANCELED, result);
        } catch (Exception error) {
            result.putString("stream", "\nReport write failed: " + error + "\n");
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
