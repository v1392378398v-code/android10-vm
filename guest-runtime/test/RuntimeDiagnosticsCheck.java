package io.a10vm.guestruntime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public final class RuntimeDiagnosticsCheck {
    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("runtime-diagnostics-");
        try {
            Files.write(directory.resolve("art.log"), "art-only\n".getBytes(StandardCharsets.UTF_8));
            Files.write(directory.resolve("framework-input.log"), "input-start-failed\n".getBytes(StandardCharsets.UTF_8));
            byte[] prefix = new byte[1024 * 1024];
            java.util.Arrays.fill(prefix, (byte) 'x');
            Path server = directory.resolve("framework-server.log");
            Files.write(server, prefix);
            Files.write(server, "\n启动失败\nlast-server-failure\n".getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.APPEND);
            String text = RuntimeDiagnostics.collect(directory.toFile());
            if (!text.contains("input-start-failed") || !text.contains("last-server-failure") || !text.contains("art-only"))
                throw new AssertionError("Persisted failure logs missing without a live session");
            if (text.length() > 8000 || text.contains("\ufffd")) throw new AssertionError("Unbounded or invalid UTF-8 tail");
            if (!RuntimeDiagnostics.collect(directory.resolve("missing").toFile()).contains("No runtime logs"))
                throw new AssertionError("Missing log directory");
            System.out.println("runtime_diagnostics_persisted_failure=passed\nruntime_diagnostics_bounded_tail=passed\nruntime_diagnostics_utf8=passed");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.list(directory)) {
                for (Path path : (Iterable<Path>) paths::iterator) Files.delete(path);
            }
            Files.delete(directory);
        }
    }
}
