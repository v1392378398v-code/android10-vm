package io.a10vm.guestruntime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public final class StartupLogCheck {
    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("startup-log-");
        try {
            StartupLog log = new StartupLog(directory.toFile());
            log.record("OLD", "before boot");
            if (!log.snapshot().lines.isEmpty()) throw new AssertionError("Events outside boot");
            log.begin();
            String firstSession = log.snapshot().session;
            for (int i = 0; i < 1000; i++) log.record("VERIFY", "file " + i);
            StartupLog.Snapshot snapshot = log.snapshot();
            if (snapshot.lines.size() != 96 || snapshot.sequence != 1001 || !snapshot.active ||
                    !snapshot.lines.get(95).endsWith("file 999")) throw new AssertionError("Snapshot bound or sequence");
            snapshot.lines.clear();
            if (log.snapshot().lines.size() != 96) throw new AssertionError("Mutable shared snapshot");
            log.record("ERROR", "启动失败\nGPU initialization");
            log.finish();
            log.record("OLD", "after boot");
            if (log.snapshot().active || log.snapshot().sequence != 1002) throw new AssertionError("Finished boot");
            String text = new String(Files.readAllBytes(directory.resolve("startup-events.log")), StandardCharsets.UTF_8);
            if (!text.contains("启动失败 GPU initialization") || text.contains("after boot") || text.contains("\ufffd"))
                throw new AssertionError("Persisted failure or UTF-8");
            log.begin();
            if (firstSession.equals(log.snapshot().session) || log.snapshot().sequence != 1 || log.snapshot().lines.size() != 1)
                throw new AssertionError("New boot reused previous events");
            text = new String(Files.readAllBytes(directory.resolve("startup-events.log")), StandardCharsets.UTF_8);
            if (text.contains("file 999") || text.contains("启动失败")) throw new AssertionError("Old session persisted");
            log.finish();
            Path blocked = directory.resolve("blocked");
            Files.write(blocked, new byte[] {1});
            StartupLog memoryOnly = new StartupLog(blocked.toFile());
            memoryOnly.begin();
            memoryOnly.record("READY", "visible despite write error");
            if (memoryOnly.snapshot().lines.size() != 2) throw new AssertionError("Log I/O interrupted boot");
            System.out.println("startup_log_bounded_snapshot=passed\nstartup_log_session_reset=passed\n" +
                    "startup_log_failure_utf8=passed\nstartup_log_write_failure=passed");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.list(directory)) {
                for (Path path : (Iterable<Path>) paths::iterator) Files.delete(path);
            }
            Files.delete(directory);
        }
    }
}
