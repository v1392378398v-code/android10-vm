package io.a10vm.guestruntime;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Locale;
import java.util.UUID;

/** Small snapshots for the boot UI, with the same events retained for diagnostics. */
public final class StartupLog {
    private static final int LIMIT = 96;
    private final File file;
    private final ArrayDeque<String> lines = new ArrayDeque<>();
    private String session = "";
    private long started, sequence;
    private boolean active;

    StartupLog(File directory) { file = new File(directory, "startup-events.log"); }

    public synchronized void begin() {
        session = UUID.randomUUID().toString();
        started = System.nanoTime();
        sequence = 0;
        lines.clear();
        active = true;
        try {
            Files.createDirectories(file.getParentFile().toPath());
            Files.write(file.toPath(), new byte[0]);
        } catch (IOException ignored) { /* UI events remain available if persistence fails. */ }
        record("BOOT", "Android 10 startup");
    }

    public synchronized void record(String stage, String message) {
        if (!active) return;
        String compact = message.replace('\n', ' ').replace('\r', ' ');
        if (compact.length() > 240) compact = compact.substring(0, 240);
        String line = String.format(Locale.ROOT, "[%06.2fs] %-7s %s",
                (System.nanoTime() - started) / 1_000_000_000.0, stage, compact);
        if (lines.size() == LIMIT) lines.removeFirst();
        lines.addLast(line);
        sequence++;
        try {
            Files.write(file.toPath(), (line + "\n").getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException ignored) { /* Logging must not interrupt a boot. */ }
    }

    public synchronized void finish() { active = false; }

    public synchronized Snapshot snapshot() {
        return new Snapshot(session, sequence, session.isEmpty() ? 0 : (System.nanoTime() - started) / 1_000_000,
                new ArrayList<>(lines), active);
    }

    public static final class Snapshot {
        public final String session;
        public final long sequence, elapsedMillis;
        public final ArrayList<String> lines;
        public final boolean active;
        private Snapshot(String session, long sequence, long elapsedMillis, ArrayList<String> lines, boolean active) {
            this.session = session;
            this.sequence = sequence;
            this.elapsedMillis = elapsedMillis;
            this.lines = lines;
            this.active = active;
        }
    }
}
