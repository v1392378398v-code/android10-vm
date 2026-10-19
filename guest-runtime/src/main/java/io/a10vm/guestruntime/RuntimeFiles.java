package io.a10vm.guestruntime;

import android.content.Context;
import android.system.Os;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Comparator;
import java.util.Map;

final class RuntimeFiles {
    private final Context context;
    private final StartupLog startupLog;
    final File nativeDirectory, directory;
    private final Map<String, String> names = new HashMap<>();
    private JSONObject manifest;

    RuntimeFiles(Context context, File directory, StartupLog startupLog) {
        this.context = context.getApplicationContext();
        this.startupLog = startupLog;
        nativeDirectory = new File(context.getApplicationInfo().nativeLibraryDir);
        this.directory = directory;
    }

    File nativeFile(String logical) throws Exception {
        inputs();
        String name = names.get(logical);
        if (name == null) throw new IllegalArgumentException("Missing runtime input: " + logical);
        return new File(nativeDirectory, name).getCanonicalFile();
    }

    JSONObject inputs() throws Exception {
        if (manifest == null) {
            try (InputStream input = context.getAssets().open("guest-runtime-inputs.json")) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
                manifest = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
            }
            JSONArray libraries = manifest.getJSONArray("files");
            for (int i = 0; i < libraries.length(); ++i) {
                JSONObject item = libraries.getJSONObject(i);
                names.put(item.getString("logical"), item.getString("name"));
            }
        }
        return manifest;
    }

    private boolean matches(File file, JSONObject item) throws Exception {
        if (!file.isFile() || file.length() != item.getLong("bytes")) return false;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(file.toPath())) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder hash = new StringBuilder();
        for (byte value : digest.digest()) hash.append(String.format("%02x", value & 0xff));
        return hash.toString().equals(item.getString("sha256"));
    }

    void verify() throws Exception {
        JSONObject inputs = inputs();
        if (inputs.getInt("guestSdk") != 29 || !inputs.getBoolean("loaderFromSource") ||
                !inputs.getBoolean("frameworkIntegrated") || inputs.getBoolean("rootRequired") ||
                !inputs.getBoolean("desktopImplemented"))
            throw new IllegalStateException("Unexpected guest runtime manifest");
        JSONArray files = inputs.getJSONArray("files");
        for (int i = 0; i < files.length(); ++i) {
            JSONObject item = files.getJSONObject(i);
            if (!matches(new File(nativeDirectory, item.getString("name")), item))
                throw new IllegalStateException("Runtime input mismatch: " + item.getString("name"));
            if ((i + 1) % 128 == 0 || i + 1 == files.length())
                startupLog.record("VERIFY", "runtime files " + (i + 1) + "/" + files.length());
        }
    }

    String dataHash(String name) throws Exception {
        JSONArray data = inputs().getJSONArray("data");
        for (int i = 0; i < data.length(); ++i) {
            JSONObject item = data.getJSONObject(i);
            if (name.equals(item.getString("name"))) return item.getString("sha256");
        }
        throw new IllegalArgumentException("Missing runtime data: " + name);
    }

    void installData() throws Exception {
        JSONObject inputs = inputs();
        JSONArray obsolete = inputs.optJSONArray("obsoleteSystemAssets");
        for (int i = 0; obsolete != null && i < obsolete.length(); i++) {
            String path = obsolete.getString(i);
            if ((!path.startsWith("rootfs/system/") && !path.startsWith("lib/")) ||
                    java.util.Arrays.asList(path.split("/")).contains(".."))
                throw new IllegalArgumentException("Unexpected obsolete system asset: " + path);
            Files.deleteIfExists(new File(directory, path).toPath());
        }
        JSONArray data = inputs.getJSONArray("data");
        for (int i = 0; i < data.length(); ++i) {
            JSONObject item = data.getJSONObject(i);
            String asset = item.getString("name");
            File file = new File(directory, item.optString("installPath", asset.substring("guest-runtime/".length())));
            if (!matches(file, item)) {
                Files.createDirectories(file.getParentFile().toPath());
                Files.deleteIfExists(file.toPath());
                try (InputStream input = context.getAssets().open(asset)) {
                    Files.copy(input, file.toPath());
                }
                if (!matches(file, item)) throw new IllegalStateException("Runtime data mismatch: " + asset);
            }
            if (item.has("mode")) Os.chmod(file.getPath(), item.getInt("mode"));
            if ((i + 1) % 256 == 0 || i + 1 == data.length())
                startupLog.record("DATA", "image files " + (i + 1) + "/" + data.length());
        }
        // Image paths that shared an inode were stored once; restore them as hard links so the
        // guest sees every path it expects without the payload carrying the bytes twice.
        JSONArray links = inputs.optJSONArray("links");
        for (int i = 0; links != null && i < links.length(); ++i) {
            JSONObject item = links.getJSONObject(i);
            File file = new File(directory, item.getString("path"));
            File target = new File(directory, item.getString("target"));
            if (target.isFile() && !file.exists()) {
                Files.createDirectories(file.getParentFile().toPath());
                try {
                    Files.createLink(file.toPath(), target.toPath());
                } catch (java.io.IOException failure) {
                    Files.copy(target.toPath(), file.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
        // Image symlinks are recreated literally: their targets are guest-absolute or relative to
        // a location that only exists inside the mapped rootfs.
        JSONArray symlinks = inputs.optJSONArray("symlinks");
        for (int i = 0; symlinks != null && i < symlinks.length(); ++i) {
            JSONObject item = symlinks.getJSONObject(i);
            File file = new File(directory, item.getString("path"));
            if (Files.isSymbolicLink(file.toPath()) &&
                    Files.readSymbolicLink(file.toPath()).toString().equals(item.getString("target"))) continue;
            Files.createDirectories(file.getParentFile().toPath());
            if (!Files.isSymbolicLink(file.toPath()) && file.isDirectory()) clearDirectory(file);
            Files.deleteIfExists(file.toPath());
            Os.symlink(item.getString("target"), file.getPath());
        }
    }

    void clearDirectory(File directory) throws Exception {
        if (!directory.exists()) return;
        try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(directory.toPath())) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                try { Files.delete(path); }
                catch (java.io.IOException failure) { throw new java.io.UncheckedIOException(failure); }
            });
        } catch (java.io.UncheckedIOException failure) {
            throw failure.getCause();
        }
    }

    void link(File path, String target) throws Exception {
        Files.createDirectories(path.getParentFile().toPath());
        Files.deleteIfExists(path.toPath());
        Os.symlink(target, path.getPath());
    }
}
