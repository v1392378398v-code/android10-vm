package io.a10vm.containerprobe;

import android.content.Context;
import android.os.Build;
import android.os.Process;
import android.system.Os;
import android.system.OsConstants;
import io.a10vm.nativedisplay.GuestLibraryFiles;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

final class LoaderProbe {
    private final Context context;
    private final File nativeDirectory;
    private final File workingDirectory;
    private final GuestLibraryFiles files;

    LoaderProbe(Context context) {
        this.context = context;
        nativeDirectory = new File(context.getApplicationInfo().nativeLibraryDir);
        workingDirectory = new File(context.getFilesDir(), "loader-stage0");
        files = new GuestLibraryFiles(context, workingDirectory);
    }

    JSONObject run(String nonce) throws Exception {
        Files.createDirectories(workingDirectory.toPath());
        JSONObject inputs = readInputs("inputs.json");
        Set<String> allowedFiles = verifyInputs(inputs.getJSONArray("files"));
        File complete = prepareRuntime("complete", false);
        File missing = prepareRuntime("missing-libc", true);
        String program = nativeFile("liba10vm-g1-payload.so").getCanonicalPath();
        String linker = nativeFile("liba10vm-a10-linker.so").getCanonicalPath();
        JSONObject host = ProbeProcess.run(workingDirectory, "host",
                Arrays.asList(program, nonce), null);
        JSONObject guest = ProbeProcess.run(workingDirectory, "guest",
                Arrays.asList(linker, program, nonce), complete);
        JSONObject missingLibc = ProbeProcess.run(workingDirectory, "missing-libc",
                Arrays.asList(linker, program, nonce), missing);

        Set<String> guestMaps = executableMaps(guest.getString("output"));
        String expectedLibc = nativeFile("liba10vm-a10-libc.so").getCanonicalPath();
        boolean mappedGuest = allowedFiles.containsAll(guestMaps)
                && guestMaps.contains(expectedLibc) && guestMaps.contains(linker)
                && guestMaps.contains(program);
        boolean guestPassed = completed(guest, nonce) && mappedGuest
                && expectedLibc.equals(canonicalValue(guest, "libc"))
                && value(guest, "host_liblog_loaded").equals("0");
        boolean hostDetected = completed(host, nonce)
                && !expectedLibc.equals(canonicalValue(host, "libc"))
                && !allowedFiles.containsAll(executableMaps(host.getString("output")));
        boolean missingRejected = !missingLibc.getBoolean("timedOut")
                && missingLibc.getInt("exitCode") != 0
                && !missingLibc.getString("output").contains("probe_complete=1")
                && missingLibc.getString("output").contains("libc.so")
                && missingLibc.getString("output").contains("not found");
        JSONObject missingContext = new JSONObject(guest.toString()).put("output",
                guest.getString("output").replaceAll("(?m)^selinux=.*$", ""));
        JSONObject wrongContext = new JSONObject(guest.toString()).put("output",
                guest.getString("output").replaceAll("(?m)^selinux=.*$", "selinux=u:r:su:s0"));
        boolean missingContextRejected = !completed(missingContext, nonce);
        boolean wrongContextRejected = !completed(wrongContext, nonce);
        return new JSONObject().put("gate", "G1-stage0-native-elf")
                .put("passed", guestPassed && hostDetected && missingRejected
                        && missingContextRejected && wrongContextRejected)
                .put("completeG1", false).put("privatePropertiesImplemented", false)
                .put("loaderFromSource", false).put("inputs", inputs)
                .put("hostSdk", Build.VERSION.SDK_INT)
                .put("targetSdk", context.getApplicationInfo().targetSdkVersion)
                .put("pageSize", Os.sysconf(OsConstants._SC_PAGESIZE))
                .put("appUid", Process.myUid()).put("nonce", nonce)
                .put("guestLibraryIsolationPassed", guestPassed)
                .put("hostControlDetected", hostDetected).put("missingLibcRejected", missingRejected)
                .put("validatorMissingContextRejected", missingContextRejected)
                .put("validatorWrongContextRejected", wrongContextRejected)
                .put("guestExecutableMappings", new JSONArray(guestMaps))
                .put("hostControl", host).put("guest", guest).put("missingLibc", missingLibc);
    }

    JSONObject readInputs(String name) throws Exception {
        return files.readInputs(name);
    }

    File nativeFile(String name) {
        return files.nativeFile(name);
    }

    Set<String> verifyInputs(JSONArray files) throws Exception {
        return this.files.verifyInputs(files);
    }

    File prepareRuntime(String name, boolean missingLibc) throws Exception {
        return files.prepareRuntime(name, missingLibc);
    }

    private static boolean completed(JSONObject run, String nonce) throws Exception {
        String uid = Integer.toString(Process.myUid());
        return Process.myUid() >= 10000 && !run.getBoolean("timedOut") && run.getInt("exitCode") == 0
                && value(run, "nonce").equals(nonce) && value(run, "uid").equals(uid)
                && value(run, "euid").equals(uid) && value(run, "cap_eff").equals("0000000000000000")
                && value(run, "selinux").matches("u:r:untrusted_app(?:_[0-9]+)?:s0(?::.*)?")
                && value(run, "math_ok").equals("1")
                && value(run, "probe_complete").equals("1");
    }

    private static String value(JSONObject run, String key) throws Exception {
        for (String line : run.getString("output").split("\n")) {
            if (line.startsWith(key + "=")) return line.substring(key.length() + 1);
        }
        return "";
    }

    private static String canonicalValue(JSONObject run, String key) throws Exception {
        String path = value(run, key);
        return path.isEmpty() ? "" : new File(path).getCanonicalPath();
    }

    static Set<String> executableMaps(String output) {
        Set<String> paths = new HashSet<>();
        for (String line : output.split("\n")) {
            if (!line.startsWith("MAP\t")) continue;
            String[] fields = line.substring(4).trim().split("\\s+", 6);
            if (fields.length == 6 && fields[1].contains("x") && fields[5].startsWith("/")) {
                paths.add(fields[5]);
            }
        }
        return paths;
    }
}
