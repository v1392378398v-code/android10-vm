package io.a10vm.guestruntime;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** One display transition; the guest system handles activity and media lifecycle changes. */
final class GuestDisplayPower {
    private final File directory, linker, appProcess;
    private final Map<String, String> environment;

    GuestDisplayPower(File directory, File linker, File appProcess, Map<String, String> environment) {
        this.directory = directory; this.linker = linker; this.appProcess = appProcess;
        this.environment = new HashMap<>(environment);
    }

    void setInteractive(boolean interactive) throws Exception {
        File log = new File(directory, "framework-display-state.log");
        ProcessBuilder builder = new ProcessBuilder(Arrays.asList(linker.getPath(), appProcess.getPath(),
                "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.GuestDisplayState",
                interactive ? "on" : "off")).directory(directory).redirectErrorStream(true).redirectOutput(log);
        builder.environment().clear();
        builder.environment().putAll(environment);
        Process child = builder.start();
        try {
            if (!child.waitFor(5, TimeUnit.SECONDS)) throw new IllegalStateException("Guest display power timeout");
            String output = new String(Files.readAllBytes(log.toPath()), StandardCharsets.UTF_8);
            if (child.exitValue() != 0 || !output.contains("guest_display_interactive=" + interactive + "\n"))
                throw new IllegalStateException("Guest display power failed: " + output);
        } finally { if (child.isAlive()) child.destroyForcibly(); }
    }
}
