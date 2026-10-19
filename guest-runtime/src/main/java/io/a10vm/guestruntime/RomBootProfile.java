package io.a10vm.guestruntime;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

final class RomBootProfile {
    private final JSONObject settings;
    private final File directory;

    RomBootProfile(JSONObject inputs, File directory) {
        settings = inputs.optJSONObject("romBoot");
        this.directory = directory;
    }

    boolean enabled() { return settings != null; }

    void configure(Map<String, String> environment) throws Exception {
        if (!enabled()) return;
        File bootstrap = new File(directory, settings.getString("bootstrapDex"));
        if (!bootstrap.isFile()) throw new IllegalStateException("Missing ROM bootstrap DEX");
        environment.put("CLASSPATH", bootstrap.getPath() + ":" + environment.get("CLASSPATH"));
        JSONArray jni = settings.getJSONArray("bootJni");
        List<String> libraries = new ArrayList<>();
        for (int i = 0; i < jni.length(); ++i) libraries.add(jni.getString(i));
        environment.put("A10VM_BOOT_JNI", String.join(":", libraries));
        if (settings.has("webviewPackage")) environment.put("A10VM_WEBVIEW_PACKAGE", settings.getString("webviewPackage"));
        if (settings.has("hardwareApplications"))
            environment.put("A10VM_HARDWARE_APPLICATIONS", settings.getJSONArray("hardwareApplications").toString());
    }

    JSONArray services() throws Exception {
        return enabled() ? settings.getJSONArray("services") : new JSONArray();
    }

    String bootEntry() {
        return enabled() ? "io.a10vm.guest.RomBootstrap" : "io.a10vm.guest.DesktopBoot";
    }

    List<String> checkArguments() {
        List<String> result = new ArrayList<>(Arrays.asList("app_process64", "-Xnoimage-dex2oat", "/system/bin",
                enabled() ? "io.a10vm.guest.RomDesktopCheck" : "io.a10vm.guest.DesktopCheck"));
        if (enabled()) result.add("200000");
        return result;
    }

    String readyMarker() { return enabled() ? "rom_desktop_ready=1" : "desktop_services_ready=1"; }
}
