package io.a10vm.nativedisplay;

import android.content.Context;
import android.system.Os;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public final class GuestLibraryFiles {
    private final Context context;
    private final File nativeDirectory, workingDirectory;
    public GuestLibraryFiles(Context context, File workingDirectory) {
        this.context = context.getApplicationContext();
        this.nativeDirectory = new File(context.getApplicationInfo().nativeLibraryDir);
        this.workingDirectory = workingDirectory;
    }
    public File nativeFile(String name) { return new File(nativeDirectory, name); }
    public JSONObject readInputs(String name) throws Exception {
        try (InputStream stream = context.getAssets().open(name)) {
            byte[] buffer = new byte[4096];
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            int count;
            while ((count = stream.read(buffer)) != -1) bytes.write(buffer, 0, count);
            return new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        }
    }
    public Set<String> verifyInputs(JSONArray files) throws Exception {
        Set<String> paths = new HashSet<>();
        for (int i = 0; i < files.length(); ++i) {
            JSONObject expected = files.getJSONObject(i);
            File file = nativeFile(expected.getString("name"));
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream stream = Files.newInputStream(file.toPath())) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = stream.read(buffer)) != -1) digest.update(buffer, 0, count);
            }
            StringBuilder actual = new StringBuilder();
            for (byte item : digest.digest()) actual.append(String.format("%02x", item & 0xff));
            if (file.length() != expected.getLong("bytes") || !actual.toString().equals(expected.getString("sha256")))
                throw new IllegalStateException("Packaged input mismatch: " + file.getName());
            paths.add(file.getCanonicalPath());
        }
        return paths;
    }
    public File prepareRuntime(String name, boolean missingLibc) throws Exception {
        File runtime = new File(workingDirectory, name), libraries = new File(runtime, "lib");
        Files.createDirectories(libraries.toPath());
        for (String library : Arrays.asList("libc", "libm", "libdl")) {
            File link = new File(libraries, library + ".so");
            Files.deleteIfExists(link.toPath());
            if (!missingLibc || !library.equals("libc"))
                Os.symlink(nativeFile("liba10vm-a10-" + library + ".so").getCanonicalPath(), link.getAbsolutePath());
        }
        String config = "dir.probe = " + nativeDirectory.getCanonicalPath() + "\n[probe]\n"
                + "namespace.default.isolated = true\nnamespace.default.search.paths = " + libraries.getCanonicalPath()
                + "\nnamespace.default.permitted.paths = " + nativeDirectory.getCanonicalPath()
                + ":" + libraries.getCanonicalPath() + "\n";
        File destination = new File(runtime, "ld.config.txt");
        Files.write(destination.toPath(), config.getBytes(StandardCharsets.UTF_8));
        return destination;
    }
}
