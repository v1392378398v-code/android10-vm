package io.a10vm.containerprobe;

import android.system.Os;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Map;

/** Private loader configuration shared by the source-built runtime probes. */
final class RuntimeConfiguration {
    private RuntimeConfiguration() { }

    static File prepare(LoaderProbe runtime, File seed, String name, String program,
            Map<String, String> libraries, String missing) throws Exception {
        File directory = new File(seed, name);
        Files.createDirectory(directory.toPath());
        for (Map.Entry<String, String> library : libraries.entrySet()) {
            if (!library.getKey().equals(missing)) {
                Os.symlink(runtime.nativeFile(library.getValue()).getCanonicalPath(),
                        new File(directory, library.getKey()).getAbsolutePath());
            }
        }
        String nativePath = new File(program).getParent();
        String text = "dir.probe = " + nativePath + "\n[probe]\nnamespace.default.isolated = true\n"
                + "namespace.default.search.paths = " + directory.getCanonicalPath() + "\n"
                + "namespace.default.permitted.paths = " + nativePath + ":" + directory.getCanonicalPath() + "\n";
        File config = new File(directory, "ld.config.txt");
        Files.write(config.toPath(), text.getBytes(StandardCharsets.UTF_8));
        return config;
    }
}
