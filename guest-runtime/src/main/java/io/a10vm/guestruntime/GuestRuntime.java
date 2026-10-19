package io.a10vm.guestruntime;

import android.content.Context;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

public final class GuestRuntime {
    private final RuntimeFiles files;
    private final StartupLog startupLog;
    private final File directory, stateRoot, rootfs, libraries, config, properties, log;

    public GuestRuntime(Context context, File directory) throws java.io.IOException {
        directory = directory.getCanonicalFile();
        this.directory = directory;
        stateRoot = context.getFilesDir().getCanonicalFile();
        startupLog = new StartupLog(directory);
        files = new RuntimeFiles(context, directory, startupLog);
        rootfs = new File(directory, "rootfs");
        libraries = new File(directory, "lib");
        config = new File(directory, "ld.config.txt");
        properties = new File(directory, "properties");
        log = new File(directory, "art.log");
    }

    public void verify() throws Exception { files.verify(); }
    public StartupLog startupLog() { return startupLog; }
    public File nativeFile(String logical) throws Exception { return files.nativeFile(logical); }

    public void configureHostDevices(java.util.Set<String> unavailableHals) throws Exception {
        if (files.inputs().has("romBoot")) {
            java.util.Set<String> unavailable = new java.util.HashSet<>(unavailableHals);
            unavailable.add("android.hardware.gnss");
            unavailable.add("vendor.qti.gnss");
            try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(new File(rootfs, "vendor/etc/vintf").toPath())) {
                for (java.nio.file.Path manifest : (Iterable<java.nio.file.Path>) paths.filter(path -> path.toString().endsWith(".xml"))::iterator)
                    HostDeviceManifest.configure(manifest, unavailable);
            }
            return;
        }
        HostDeviceManifest.configure(new File(rootfs, "vendor/etc/vintf/manifest/a10vm-host-devices.xml").toPath(),
                unavailableHals);
    }

    public void prepare() throws Exception {
        verify();
        files.installData();
        JSONArray directories = files.inputs().getJSONArray("initialDirectories");
        for (int i = 0; i < directories.length(); ++i)
            Files.createDirectories(new File(rootfs, directories.getString(i)).toPath());
        Map<String, String> aliases = new java.util.LinkedHashMap<>();
        aliases.put("apex/com.android.runtime", "/system/apex/com.android.runtime.debug");
        for (String name : Arrays.asList("com.android.conscrypt", "com.android.media", "com.android.media.swcodec", "com.android.resolv", "com.android.tzdata"))
            aliases.put("apex/" + name, "/system/apex/" + name);
        aliases.put("product", "/system/product");
        aliases.put("etc", "/system/etc");
        aliases.put("data/data", "/data/user/0");
        JSONObject romAliases = files.inputs().optJSONObject("rootfsAliases");
        if (romAliases != null)
            for (java.util.Iterator<String> names = romAliases.keys(); names.hasNext();) {
                String name = names.next();
                aliases.put(name, romAliases.getString(name));
            }
        for (Map.Entry<String, String> alias : aliases.entrySet())
            files.link(new File(rootfs, alias.getKey()), alias.getValue());
        File sockets = new File(directory, "sock");
        Files.createDirectories(sockets.toPath());
        files.link(new File(rootfs, "dev/socket"), sockets.getPath());
        JSONArray inputs = files.inputs().getJSONArray("files");
        for (int i = 0; i < inputs.length(); ++i) {
            JSONObject item = inputs.getJSONObject(i);
            String logical = item.getString("logical");
            String library = item.optString("libraryName", logical.endsWith(".so") ? logical : "");
            if (!library.isEmpty()) {
                files.link(new File(libraries, library), nativeFile(logical).getPath());
                files.link(new File(rootfs, "system/lib64/" + library), nativeFile(logical).getPath());
            }
            if (item.has("guestPath"))
                files.link(new File(rootfs, item.getString("guestPath").substring(1)), nativeFile(logical).getPath());
        }
        JSONArray nativeLinks = files.inputs().optJSONArray("nativeLinks");
        for (int i = 0; nativeLinks != null && i < nativeLinks.length(); ++i) {
            JSONObject item = nativeLinks.getJSONObject(i);
            files.link(new File(directory, item.getString("path")), nativeFile(item.getString("logical")).getPath());
        }
        String nativePath = files.nativeDirectory.getCanonicalPath();
        String allowed = nativePath + ":" + directory.getCanonicalPath();
        java.util.List<String> namespaces = new ArrayList<>(Arrays.asList("runtime", "conscrypt", "media", "swcodec"));
        if (files.inputs().has("romBoot")) namespaces.addAll(Arrays.asList("vndk", "sphal"));
        String text = "dir.guest = " + nativePath + "\ndir.guest = " + directory.getCanonicalPath()
                + "\n[guest]\nadditional.namespaces = " + String.join(",", namespaces) + "\n"
                + "namespace.default.isolated = true\nnamespace.default.search.paths = " + libraries.getPath() + "\n"
                + "namespace.default.permitted.paths = " + allowed + "\n";
        for (String name : namespaces)
            text += "namespace." + name + ".visible = true\nnamespace." + name + ".isolated = true\n"
                    + "namespace." + name + ".search.paths = " + libraries.getPath() + "\n"
                    + "namespace." + name + ".permitted.paths = " + allowed + "\n"
                    + "namespace." + name + ".links = default\nnamespace." + name + ".link.default.allow_all_shared_libs = true\n";
        Files.write(config.toPath(), text.getBytes(StandardCharsets.UTF_8));
        File seedLog = new File(directory, "seed.log");
        String seedInputs = "seed_inputs=" + files.dataHash("guest-runtime/guest.prop") + "\n";
        if (!seedLog.isFile() || !new String(Files.readAllBytes(seedLog.toPath()), StandardCharsets.UTF_8)
                .contains(seedInputs)) {
            files.clearDirectory(properties);
            ProcessBuilder seed = new ProcessBuilder(nativeFile("seed-properties").getPath(),
                    properties.getPath(), new File(directory, "guest.prop").getPath())
                    .redirectErrorStream(true).redirectOutput(seedLog);
            seed.environment().clear();
            seed.environment().put("PATH", "/system/bin");
            try { run(seed, "属性初始化", 5); }
            catch (Exception failure) {
                String detail = seedLog.isFile() ? new String(Files.readAllBytes(seedLog.toPath()), StandardCharsets.UTF_8) : "";
                throw new IllegalStateException("属性初始化失败：" + detail, failure);
            }
            Files.write(seedLog.toPath(), seedInputs.getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.APPEND);
        }
    }

    public FrameworkSession startFramework(String nonce) throws Exception {
        return startSession(nonce, false);
    }

    public FrameworkSession startDesktop(String nonce) throws Exception {
        return startSession(nonce, true);
    }

    public FrameworkSession startDesktop(String nonce, File graphicsSocket, File inputSocket) throws Exception {
        FrameworkSession session = new FrameworkSession(this, files, directory, graphicsSocket, inputSocket);
        try { session.start(nonce, true); return session; }
        catch (Exception failure) {
            try { session.close(); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    private FrameworkSession startSession(String nonce, boolean desktop) throws Exception {
        FrameworkSession session = new FrameworkSession(this, files, directory);
        try { session.start(nonce, desktop); return session; }
        catch (Exception failure) {
            try { session.close(); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    public Map<String, String> environment() throws Exception {
        Map<String, String> environment = new HashMap<>();
        environment.put("PATH", "/system/bin");
        environment.put("TMPDIR", directory.getPath());
        environment.put("ANDROID_ROOT", "/system");
        environment.put("ANDROID_DATA", "/data");
        environment.put("ANDROID_STORAGE", "/storage");
        environment.put("EXTERNAL_STORAGE", "/storage/emulated/0");
        environment.put("ASEC_MOUNTPOINT", "/mnt/asec");
        environment.put("ANDROID_RUNTIME_ROOT", "/apex/com.android.runtime");
        environment.put("ANDROID_TZDATA_ROOT", "/apex/com.android.tzdata");
        environment.put("A10VM_ROOTFS", rootfs.getPath());
        environment.put("A10VM_HOST_ROOT", files.nativeDirectory.getCanonicalPath());
        environment.put("A10VM_STATE_ROOT", stateRoot.getPath());
        environment.put("A10VM_HOST_NETWORK", "1");
        environment.put("A10VM_PROPERTIES", properties.getPath());
        environment.put("A10VM_LD_CONFIG", config.getPath());
        environment.put("A10VM_EXEC_LINKER", nativeFile("ld-android.so").getPath());
        return environment;
    }

    public String checkJava(String nonce) throws Exception {
        ArrayList<String> command = new ArrayList<>(Arrays.asList(nativeFile("ld-android.so").getPath(),
                nativeFile("dalvikvm64").getPath(), "-Xnoimage-dex2oat",
                "-Xbootclasspath:/apex/com.android.runtime/javalib/core-oj.jar:/apex/com.android.runtime/javalib/core-libart.jar",
                "-Djava.library.path=" + libraries.getPath(), "-cp", new File(directory, "runtime-check.dex").getPath(),
                "io.a10vm.guest.RuntimeCheck", nonce));
        ProcessBuilder builder = new ProcessBuilder(command).directory(directory).redirectErrorStream(true).redirectOutput(log);
        builder.environment().clear();
        builder.environment().putAll(environment());
        builder.environment().put("LD_PRELOAD", nativeFile("liba10vm-guest-log.so").getPath());
        try { run(builder, "Android 10 ART", 10); }
        catch (Exception failure) { throw new IllegalStateException("ART 启动失败：" + logs(), failure); }
        String output = logs();
        RuntimeIdentity.verifyArt(output, nonce, files, new File(rootfs, "data/local/tmp/runtime-check.txt"));
        return "Android 10 ART 已通过线程和文件读写检查。";
    }

    private static void run(ProcessBuilder builder, String stage, int seconds) throws Exception {
        Process process = builder.start();
        try {
            if (!process.waitFor(seconds, TimeUnit.SECONDS)) throw new IllegalStateException(stage + " 超时");
            if (process.exitValue() != 0) throw new IllegalStateException(stage + " 退出 code=" + process.exitValue());
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
                process.waitFor(2, TimeUnit.SECONDS);
            }
        }
    }

    public String logs() throws Exception {
        return log.isFile() ? new String(Files.readAllBytes(log.toPath()), StandardCharsets.UTF_8) : "";
    }

    public String diagnostics() { return RuntimeDiagnostics.collect(directory); }
}
