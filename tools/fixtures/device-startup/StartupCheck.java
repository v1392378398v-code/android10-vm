package io.a10vm.devicecheck;

import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Start the actual private service as its app UID on devices without shell input access. */
public final class StartupCheck extends Instrumentation {
    private boolean memoryPriority;

    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        memoryPriority = args != null && "memory-priority".equals(args.getString("check"));
        start();
    }

    private String read(File file) throws Exception {
        return file.isFile() ? new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8) : "";
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (memoryPriority) {
                File files = getTargetContext().getFilesDir();
                ClassLoader loader = new dalvik.system.DexClassLoader(
                        new File(files, "memory-priority-check.dex").getPath(),
                        getTargetContext().getCodeCacheDir().getPath(), null, getClass().getClassLoader());
                loader.loadClass("io.a10vm.guest.GuestMemoryPriorityCheck")
                        .getMethod("main", String[].class).invoke(null, (Object) new String[] {files.getPath()});
                result.putString("appUid", Integer.toString(android.os.Process.myUid()));
                result.putString("selinux", read(new File("/proc/self/attr/current")).trim());
                result.putString("check", "memory-priority");
                result.putString("passed", "true");
                finish(-1, result);
                return;
            }
            String target = getTargetContext().getPackageName();
            getTargetContext().startActivity(new Intent().setClassName(target, "io.a10vm.ui.MainActivity")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            SystemClock.sleep(1500);
            File directory = new File(getTargetContext().getFilesDir(), "guest-runtime");
            File server = new File(directory, "framework-server.log");
            File client = new File(directory, "framework-client.log");
            String previous = read(server);
            String previousClient = read(client);
            getTargetContext().startForegroundService(new Intent()
                    .setClassName(target, "io.a10vm.runtime.VmService").setAction("io.a10vm.START_NATIVE_DISPLAY"));
            result.putString("stage", "service-start-requested");
            sendStatus(0, result);
            long deadline = SystemClock.elapsedRealtime() + 180000;
            while (true) {
                String log = read(server);
                boolean fresh = !log.equals(previous);
                if (fresh && (log.contains("Failure starting core service") ||
                        log.contains("*** FATAL EXCEPTION IN SYSTEM PROCESS:")))
                    throw new AssertionError(log.substring(Math.max(0, log.length() - 10000)));
                String check = read(client);
                if (fresh && !check.equals(previousClient) && check.contains("rom_desktop_ready=1\n")) {
                    Matcher pid = Pattern.compile("(?m)^desktop_pid=(\\d+)$").matcher(log);
                    if (!pid.find()) throw new AssertionError("Guest system server PID missing");
                    String status = read(new File("/proc/" + pid.group(1) + "/status"));
                    if (!status.contains("CapEff:\t0000000000000000"))
                        throw new AssertionError("Guest capabilities: " + status);
                    result.putString("systemServerPid", pid.group(1));
                    result.putString("appUid", Integer.toString(android.os.Process.myUid()));
                    getTargetContext().startActivity(new Intent().setClassName(target, "io.a10vm.ui.FullscreenActivity")
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    result.putString("desktop", "ready");
                    sendStatus(0, result);
                    SystemClock.sleep(30000);
                    if (!new File("/proc/" + pid.group(1)).isDirectory())
                        throw new AssertionError("Guest system server exited during stability check");
                    result.putString("passed", "true");
                    finish(-1, result);
                    return;
                }
                if (SystemClock.elapsedRealtime() >= deadline) throw new AssertionError("Desktop startup timeout");
                SystemClock.sleep(250);
            }
        } catch (Throwable error) {
            while (error instanceof java.lang.reflect.InvocationTargetException && error.getCause() != null)
                error = error.getCause();
            result.putString("passed", "false");
            result.putString("error", error.toString());
            finish(0, result);
        }
    }
}
