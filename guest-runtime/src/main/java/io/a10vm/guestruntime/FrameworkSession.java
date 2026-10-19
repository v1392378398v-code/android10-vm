package io.a10vm.guestruntime;

import android.os.SystemClock;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

public final class FrameworkSession implements AutoCloseable {
    private static final int ART_STARTUP_SECONDS = 30;
    private final GuestRuntime runtime;
    private final RuntimeFiles files;
    private final File directory;
    private final File externalGraphics, inputSocket;
    private final Map<String, Process> children = new LinkedHashMap<>();
    private final Map<String, File> logs = new LinkedHashMap<>();
    private final List<String> romServices = new ArrayList<>();
    private Map<String, String> desktopEnvironment;

    FrameworkSession(GuestRuntime runtime, RuntimeFiles files, File directory) {
        this(runtime, files, directory, null, null);
    }

    FrameworkSession(GuestRuntime runtime, RuntimeFiles files, File directory, File graphicsSocket, File inputSocket) {
        this.runtime = runtime;
        this.files = files;
        this.directory = directory;
        this.externalGraphics = graphicsSocket;
        this.inputSocket = inputSocket;
    }

    void start(String nonce, boolean desktop) throws Exception {
        File bootProperties = new File(directory, "boot-properties");
        File propertySocket = new File(directory, "property.sock");
        files.clearDirectory(bootProperties);
        Files.deleteIfExists(propertySocket.toPath());
        Process properties = launch("properties", Arrays.asList("property-service", bootProperties.getPath(),
                new File(directory, "guest.prop").getPath(), propertySocket.getPath()), runtime.environment());
        await("properties", properties, "property_service_ready=1", 3);
        RuntimeIdentity.verifyProcess(processPid("properties", "property_service_pid"), files);
        File socket = new File(directory, "binder.sock");
        Files.deleteIfExists(socket.toPath());
        Map<String, String> registry = registryEnvironment(socket);
        registry.put("A10VM_PROPERTIES", bootProperties.getPath());
        Process broker = launch("broker", Arrays.asList("binder-broker", socket.getPath()), registry);
        await("broker", broker, "binder_broker_ready=1", 3);
        RuntimeIdentity.verifyProcess(processPid("broker", "binder_broker_pid"), files);
        Map<String, String> framework = runtime.environment();
        framework.put("A10VM_PROPERTIES", bootProperties.getPath());
        framework.put("A10VM_PROPERTY_SOCKET", propertySocket.getPath());
        framework.put("A10VM_BINDER_PATH", socket.getPath());
        framework.put("LD_PRELOAD", files.nativeFile("liba10vm-property-client.so").getPath() + ":" +
                files.nativeFile("liba10vm-hal-modules.so").getPath() + ":" +
                files.nativeFile("liba10vm-guest-devices.so").getPath() + ":" +
                files.nativeFile("liba10vm-binder-devices.so").getPath() + ":" +
                files.nativeFile("liba10vm-guest-log.so").getPath() + ":" +
                files.nativeFile("libandroid_runtime.so").getPath() + ":" +
                files.nativeFile("libutils.so").getPath() + ":" +
                files.nativeFile("libbinder.so").getPath() + ":" +
                files.nativeFile("libhwbinder.so").getPath() + ":" +
                files.nativeFile("libhidlbase.so").getPath());
        framework.put("CLASSPATH", new File(directory, "framework-check.dex").getPath());
        JSONArray boot = files.inputs().getJSONArray("bootClassPath");
        List<String> paths = new ArrayList<>();
        for (int i = 0; i < boot.length(); ++i) paths.add(boot.getString(i));
        framework.put("BOOTCLASSPATH", String.join(":", paths));
        Map<String, String> managerEnvironment = new HashMap<>(framework);
        managerEnvironment.put("LD_PRELOAD", files.nativeFile("liba10vm-manager-policy.so").getPath() + ":" +
                framework.get("LD_PRELOAD"));
        Process manager = launch("manager", Arrays.asList("servicemanager"), managerEnvironment);
        await("manager", manager, "binder_context_ready=1", 3);
        RuntimeIdentity.verifyProcess(processPid("manager", "binder_context_pid"), files);
        File hardwareSocket = new File(directory, "hwbinder.sock");
        Files.deleteIfExists(hardwareSocket.toPath());
        Process hardwareBroker = launch("hwbroker", Arrays.asList("binder-broker", hardwareSocket.getPath()), registry);
        await("hwbroker", hardwareBroker, "binder_broker_ready=1", 3);
        RuntimeIdentity.verifyProcess(processPid("hwbroker", "binder_broker_pid"), files);
        framework.put("A10VM_HWBINDER_PATH", hardwareSocket.getPath());
        managerEnvironment.put("A10VM_HWBINDER_PATH", hardwareSocket.getPath());
        Process hardwareManager = launch("hwmanager", Arrays.asList("hwservicemanager"), managerEnvironment);
        await("hwmanager", hardwareManager, "binder_context_ready=1", 3);
        RuntimeIdentity.verifyProcess(processPid("hwmanager", "binder_context_pid"), files);
        if (desktop) {
            startDesktop(framework);
            return;
        }
        Process server = launch("server", command("Server", nonce), framework);
        await("server", server, "framework_service_registered=" + nonce, 10);
        RuntimeIdentity.verifyProcess(processPid("server", "framework_pid"), files);
        Process client = launch("client", command("Client", nonce), framework);
        await("client", client, "framework_complete=1", 10);
        RuntimeIdentity.verifyProcess(processPid("client", "framework_pid"), files);
        if (!client.waitFor(3, TimeUnit.SECONDS) || client.exitValue() != 0)
            throw new IllegalStateException("Framework client exit: " + readLog("client"));
        RuntimeIdentity.verifyFramework(readLog("client"), nonce, files);
        children.remove("client");
        if (!isAlive()) throw new IllegalStateException("Framework service stopped during startup");
    }

    private void startDesktop(Map<String, String> environment) throws Exception {
        RomBootProfile profile = new RomBootProfile(files.inputs(), directory);
        File graphicsSocket = externalGraphics == null ? new File(directory, "gpu.sock") : externalGraphics;
        if (externalGraphics == null) {
            Files.deleteIfExists(graphicsSocket.toPath());
            File gpuLog = new File(directory, "framework-gpu.log");
            ProcessBuilder gpuBuilder = new ProcessBuilder(files.nativeFile("desktop-gpu-host").getPath(),
                    graphicsSocket.getPath()).directory(directory).redirectErrorStream(true).redirectOutput(gpuLog);
            gpuBuilder.environment().clear();
            gpuBuilder.environment().put("PATH", "/system/bin");
            Process gpu = gpuBuilder.start();
            children.put("gpu", gpu);
            logs.put("gpu", gpuLog);
            await("gpu", gpu, "desktop_gpu_ready=1", 3);
        }
        environment.put("A10VM_GPU_SOCKET", graphicsSocket.getPath());
        environment.put("A10VM_GUEST_UID", "1000");
        environment.put("A10VM_GUEST_GID", "1000");
        environment.put("A10VM_APP_PROCESS", files.nativeFile("app_process64").getPath());
        environment.put("A10VM_LIBRARY_PATH", new File(directory, "lib").getPath());
        if (!profile.enabled()) {
            File keys = new File(directory, "rootfs/data/misc/keystore");
            Files.createDirectories(keys.toPath());
            android.system.Os.chmod(keys.getPath(), 0700);
            Map<String, String> keyEnvironment = new HashMap<>(environment);
            keyEnvironment.put("A10VM_GUEST_UID", "9999");
            keyEnvironment.put("A10VM_GUEST_GID", "9999");
            Process keymaster = launch("keymaster", Arrays.asList(
                    "image/vendor/bin/hw/android.hardware.keymaster@3.0-service"), keyEnvironment);
            await("keymaster", keymaster,
                    "Registration complete for android.hardware.keymaster@3.0::IKeymasterDevice/default.", 5);
            keyEnvironment.put("A10VM_GUEST_UID", "1017");
            keyEnvironment.put("A10VM_GUEST_GID", "1017");
            Process keystore = launch("keystore", Arrays.asList("image/system/bin/keystore", "/data/misc/keystore"),
                    keyEnvironment);
            await("keystore", keystore, "with interface name default and seclevel SOFTWARE", 5);
            environment.put("A10VM_NATIVE_KEYSTORE", "1");
        }
        Process suspend = launch("suspend", Arrays.asList("system-suspend"), environment);
        launch("composer", Arrays.asList("graphics-composer"), environment);
        launch("allocator", Arrays.asList("graphics-allocator"), environment);
        launch("configstore", Arrays.asList("graphics-configstore"), environment);
        if (profile.enabled()) launch("health", Arrays.asList("health"), environment);
        launch("idmap", Arrays.asList("idmap2d"), environment);
        Process devices = launch("host-devices", Arrays.asList("host-devices"), environment);
        await("host-devices", devices, "host_devices_ready=1", 5);
        if (files.inputs().optBoolean("hostCameraBridge")) {
            Map<String, String> cameraEnvironment = new HashMap<>(environment);
            cameraEnvironment.put("A10VM_GUEST_UID", "1047");
            cameraEnvironment.put("A10VM_GUEST_GID", "1005");
            Process provider = launch("camera-provider", Arrays.asList("camera-provider"), cameraEnvironment);
            await("camera-provider", provider, "host_camera_provider_ready=1", 8);
            launch("camera", Arrays.asList("cameraserver"), cameraEnvironment);
        }
        Map<String, String> audioEnvironment = new HashMap<>(environment);
        audioEnvironment.put("A10VM_GUEST_UID", "1041");
        audioEnvironment.put("A10VM_GUEST_GID", "1005");
        launch("audio-hal", Arrays.asList("audio-hal"), audioEnvironment);
        launch("audio", Arrays.asList("audioserver"), audioEnvironment);
        Map<String, String> mediaEnvironment = new HashMap<>(environment);
        mediaEnvironment.put("A10VM_GUEST_UID", "1013");
        mediaEnvironment.put("A10VM_GUEST_GID", "1005");
        for (String role : Arrays.asList("media-extractor", "media-metrics", "media-drm", "drm", "media-omx", "media-codec", "media"))
            launch(role, Arrays.asList(role), mediaEnvironment);
        Map<String, String> installerEnvironment = new HashMap<>(environment);
        installerEnvironment.put("A10VM_GUEST_UID", "0");
        installerEnvironment.put("A10VM_GUEST_GID", "0");
        launch("installer", Arrays.asList("installd"), installerEnvironment);
        JSONArray services = profile.services();
        for (int i = 0; i < services.length(); ++i) {
            JSONObject service = services.getJSONObject(i);
            Map<String, String> serviceEnvironment = new HashMap<>(environment);
            serviceEnvironment.put("A10VM_GUEST_UID", service.getString("uid"));
            serviceEnvironment.put("A10VM_GUEST_GID", service.getString("gid"));
            serviceEnvironment.put("LD_PRELOAD", files.nativeFile(service.getString("preload")).getPath() + ":" +
                    environment.get("LD_PRELOAD"));
            String role = service.getString("role");
            List<String> serviceCommand = new ArrayList<>();
            serviceCommand.add(service.getString("logical"));
            JSONArray arguments = service.optJSONArray("arguments");
            if (arguments != null) for (int j = 0; j < arguments.length(); ++j)
                serviceCommand.add(arguments.getString(j));
            launch(role, serviceCommand, serviceEnvironment);
            romServices.add(role);
        }
        launch("compositor", Arrays.asList("surfaceflinger"), environment);
        List<String> paths = new ArrayList<>();
        paths.add(new File(directory, "framework-check.dex").getPath());
        JSONArray classpath = files.inputs().getJSONArray("systemServerClassPath");
        for (int i = 0; i < classpath.length(); ++i) paths.add(classpath.getString(i));
        environment.put("SYSTEMSERVERCLASSPATH", String.join(":", paths.subList(1, paths.size())));
        if (profile.enabled()) environment.put("CLASSPATH", String.join(":", paths));
        profile.configure(environment);
        desktopEnvironment = new HashMap<>(environment);
        Map<String, String> serverEnvironment = new HashMap<>(environment);
        if (!profile.enabled()) serverEnvironment.put("CLASSPATH", String.join(":", paths));
        Process server = launch("server", Arrays.asList("app_process64",
                "-Xnoimage-dex2oat", "-Da10vm.bootSetupTimeoutMs=210000",
                "-Djava.library.path=" + new File(directory, "lib").getPath(),
                "/system/bin", profile.bootEntry()), serverEnvironment);
        try {
            int pid = awaitPid(server, "desktop_pid", ART_STARTUP_SECONDS);
            RuntimeIdentity.verifyProcess(pid, files);
            Process check = launch("client", profile.checkArguments(), environment);
            await("client", check, profile.readyMarker(), 205);
            if (!check.waitFor(2, TimeUnit.SECONDS) || check.exitValue() != 0 || !server.isAlive())
                throw new IllegalStateException("Desktop services did not remain running");
            children.remove("client");
            if (inputSocket != null) {
                Process input = launch("input", Arrays.asList("app_process64",
                        "-Xnoimage-dex2oat", "/system/bin", "io.a10vm.guest.DesktopInput", inputSocket.getPath()), environment);
                await("input", input, "desktop_input_ready=1", ART_STARTUP_SECONDS);
                RuntimeIdentity.verifyProcess(processPid("input", "desktop_input_pid"), files);
            }
        } catch (Exception failure) {
            StringBuilder detail = new StringBuilder();
            for (String role : Arrays.asList("client", "input", "gpu", "composer", "allocator", "installer", "compositor", "server")) {
                String text = readLog(role);
                detail.append('\n').append(role).append(":\n").append(text.substring(Math.max(0, text.length() - 2200)));
            }
            throw new IllegalStateException("Android 10 桌面启动阻塞：" + failure.getMessage() + "\n" + detail, failure);
        }
    }

    private int awaitPid(Process server, String key, int seconds) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + seconds * 1000L;
        while (!readLog("server").contains(key + "=")) {
            if (!server.isAlive() || SystemClock.elapsedRealtime() >= deadline)
                throw new IllegalStateException("Missing desktop process identity");
            Thread.sleep(10);
        }
        return processPid("server", key);
    }

    private List<String> command(String role, String nonce) {
        return Arrays.asList("app_process64", "-Xnoimage-dex2oat",
                "/system/bin", "io.a10vm.guest.Framework" + role, nonce);
    }

    private Map<String, String> registryEnvironment(File socket) throws Exception {
        File libraries = new File(directory, "registry-lib");
        JSONObject mapping = files.inputs().getJSONObject("registryLibraries");
        for (java.util.Iterator<String> names = mapping.keys(); names.hasNext();) {
            String name = names.next();
            files.link(new File(libraries, name), files.nativeFile(mapping.getString(name)).getPath());
        }
        File config = new File(directory, "registry.config.txt");
        String nativePath = files.nativeDirectory.getCanonicalPath();
        String text = "dir.registry = " + nativePath + "\n[registry]\n"
                + "namespace.default.isolated = true\nnamespace.default.search.paths = " + libraries.getPath() + "\n"
                + "namespace.default.permitted.paths = " + nativePath + ":" + directory.getPath() + "\n";
        Files.write(config.toPath(), text.getBytes(StandardCharsets.UTF_8));
        Map<String, String> environment = runtime.environment();
        environment.put("A10VM_LD_CONFIG", config.getPath());
        environment.put("A10VM_BINDER_PATH", socket.getPath());
        return environment;
    }

    private Process launch(String role, List<String> arguments, Map<String, String> environment) throws Exception {
        List<String> command = new ArrayList<>();
        command.add(files.nativeFile("ld-android.so").getPath());
        command.add(files.nativeFile(arguments.get(0)).getPath());
        command.addAll(arguments.subList(1, arguments.size()));
        File log = new File(directory, "framework-" + role + ".log");
        logs.put(role, log);
        ProcessBuilder builder = new ProcessBuilder(command).directory(new File(directory, "rootfs")).redirectErrorStream(true).redirectOutput(log);
        builder.environment().clear();
        builder.environment().putAll(environment);
        Process child = builder.start();
        children.put(role, child);
        runtime.startupLog().record("SPAWN", role + " process started");
        return child;
    }

    private void await(String role, Process child, String marker, int seconds) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + seconds * 1000L;
        long nextNotice = SystemClock.elapsedRealtime() + 3000;
        while (!readLog(role).contains(marker + "\n")) {
            if (children.containsKey("compositor")) {
                for (String service : Arrays.asList("gpu", "composer", "allocator", "compositor", "host-devices", "server")) {
                    Process dependency = children.get(service);
                    if (dependency != null && !dependency.isAlive())
                        throw new IllegalStateException("Desktop " + service + " exited: " + readLog(service));
                }
            }
            if (!child.isAlive()) throw new IllegalStateException("Framework " + role + " exited: " + readLog(role));
            if (SystemClock.elapsedRealtime() >= deadline) throw new IllegalStateException("Framework " + role + " timeout: " + readLog(role));
            if (SystemClock.elapsedRealtime() >= nextNotice) {
                runtime.startupLog().record("WAIT", role + ": waiting for " + marker);
                nextNotice = SystemClock.elapsedRealtime() + 3000;
            }
            Thread.sleep(10);
        }
        runtime.startupLog().record("READY", role + ": " + marker);
    }

    public boolean isAlive() {
        for (String role : romServices)
            if (!children.get(role).isAlive()) return false;
        for (String role : Arrays.asList("gpu", "suspend", "composer", "allocator", "configstore", "compositor",
                "host-devices", "keymaster", "keystore"))
            if (children.containsKey(role) && !children.get(role).isAlive()) return false;
        return Arrays.asList("properties", "broker", "manager", "hwbroker", "hwmanager", "server").stream()
                .map(children::get).allMatch(child -> child != null && child.isAlive());
    }

    public void setDisplayInteractive(boolean interactive) throws Exception {
        if (!isAlive() || desktopEnvironment == null) return;
        new GuestDisplayPower(directory, files.nativeFile("ld-android.so"), files.nativeFile("app_process64"),
                desktopEnvironment).setInteractive(interactive);
    }

    public String installApk(File apk) throws Exception {
        return installApks(java.util.Collections.singletonList(apk));
    }

    public String installApks(List<File> apks) throws Exception {
        if (apks.isEmpty()) throw new IllegalArgumentException("Expected APK files");
        if (!isAlive() || desktopEnvironment == null) throw new IllegalStateException("请先启动 Android 10");
        Map<String, String> environment = new HashMap<>(desktopEnvironment);
        environment.put("A10VM_GUEST_UID", "1000");
        environment.put("A10VM_GUEST_GID", "1000");
        List<String> arguments = new ArrayList<>(Arrays.asList("app_process64", "-Xnoimage-dex2oat",
                "/system/bin", "io.a10vm.guest.GuestInstall"));
        for (File apk : apks) arguments.add(apk.getCanonicalPath());
        Process command = launch("install", arguments, environment);
        try {
            if (!command.waitFor(130L + 125L * apks.size(), TimeUnit.SECONDS))
                throw new IllegalStateException("应用安装超时");
            String output = readLog("install");
            if (command.exitValue() != 0 || !output.contains("guest_install_complete=1\n"))
                throw new IllegalStateException(output);
            return output;
        } finally {
            if (command.isAlive()) command.destroyForcibly();
            children.remove("install");
        }
    }

    public void scanMedia(String path) throws Exception {
        if (!isAlive() || desktopEnvironment == null) throw new IllegalStateException("请先启动 Android 10");
        Map<String, String> environment = new HashMap<>(desktopEnvironment);
        Process scanner = launch("media-scan", Arrays.asList("app_process64", "-Xnoimage-dex2oat",
                "/system/bin", "io.a10vm.guest.GuestMediaScan", path), environment);
        try {
            if (!scanner.waitFor(35, TimeUnit.SECONDS)) throw new IllegalStateException("客体媒体扫描超时");
            String output = readLog("media-scan");
            if (scanner.exitValue() != 0 || !output.contains("guest_media_scan_complete=1"))
                throw new IllegalStateException("客体媒体扫描失败：" + output);
        } finally { scanner.destroy(); children.remove("media-scan"); }
    }

    public String error() {
        // The touch injector is a peripheral: losing it degrades input but leaves the desktop
        // usable, so it is reported through the input channel rather than tearing down the session.
        for (Map.Entry<String, Process> child : children.entrySet()) {
            if (child.getKey().equals("input")) continue;
            if (!child.getValue().isAlive()) return "Android 10 框架进程退出：" + child.getKey() + " code=" + child.getValue().exitValue();
        }
        return "";
    }

    private String readLog(String role) throws Exception {
        File file = logs.get(role);
        return file != null && file.isFile() ? new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8) : "";
    }

    private int processPid(String role, String key) throws Exception {
        String prefix = key + "=";
        for (String line : readLog(role).split("\\n")) {
            if (line.startsWith(prefix)) {
                try { return Integer.parseInt(line.substring(prefix.length()).trim()); }
                catch (NumberFormatException ignored) { break; }
            }
        }
        throw new IllegalStateException("Missing process identity: " + key + " in " + role);
    }

    public String logs() throws Exception {
        StringBuilder output = new StringBuilder();
        for (String role : logs.keySet()) output.append("\nFRAMEWORK ").append(role).append('\n').append(readLog(role));
        return output.toString();
    }

    @Override public void close() throws Exception {
        List<Process> processes = new ArrayList<>(children.values());
        children.clear();
        Exception failure = null;
        for (int i = processes.size() - 1; i >= 0; --i) {
            Process child = processes.get(i);
            try {
                if (child.isAlive()) child.destroy();
                if (!child.waitFor(2, TimeUnit.SECONDS)) {
                    child.destroyForcibly();
                    if (!child.waitFor(2, TimeUnit.SECONDS)) throw new IllegalStateException("Framework child stop timeout");
                }
            } catch (Exception problem) {
                child.destroyForcibly();
                if (failure == null) failure = problem;
                else failure.addSuppressed(problem);
            }
        }
        if (failure != null) throw failure;
    }
}
