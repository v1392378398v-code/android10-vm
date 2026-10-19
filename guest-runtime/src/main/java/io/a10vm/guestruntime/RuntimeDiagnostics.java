package io.a10vm.guestruntime;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Read bounded persisted tails, including sessions that failed before attachment. */
final class RuntimeDiagnostics {
    private static final int TAIL_BYTES = 6144;

    static String collect(File directory) {
        StringBuilder text = new StringBuilder();
        for (String name : new String[] {"session-state.log", "startup-events.log", "framework-client.log", "framework-input.log",
                "framework-server.log", "framework-compositor.log", "framework-allocator.log",
                "framework-composer.log", "framework-broker.log", "framework-host-devices.log",
                "framework-display-state.log", "art.log", "seed.log"})
            append(text, new File(directory, name));
        File[] applications = directory.listFiles((parent, name) ->
                name.startsWith("application-") && name.endsWith(".log"));
        if (applications != null) {
            File newest = null, previous = null;
            long newestTime = Long.MIN_VALUE, previousTime = Long.MIN_VALUE;
            for (File file : applications) {
                long modified = file.lastModified();
                if (modified >= newestTime) {
                    previous = newest; previousTime = newestTime;
                    newest = file; newestTime = modified;
                } else if (modified >= previousTime) { previous = file; previousTime = modified; }
            }
            if (newest != null) append(text, newest);
            if (previous != null) append(text, previous);
        }
        return text.length() == 0 ? "No runtime logs have been created.\n" : text.toString();
    }

    private static void append(StringBuilder text, File file) {
        if (!file.isFile()) return;
        text.append("\n--- ").append(file.getName()).append(" | ")
                .append(new SimpleDateFormat("MM-dd HH:mm:ss", Locale.ROOT).format(new Date(file.lastModified())))
                .append(" ---\n");
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            long length = input.length();
            int size = (int) Math.min(length, TAIL_BYTES);
            byte[] bytes = new byte[size];
            input.seek(length - size);
            input.readFully(bytes);
            int start = 0;
            while (start < size && (bytes[start] & 0xc0) == 0x80) start++;
            if (length > size) text.append("[recent tail]\n");
            text.append(new String(bytes, start, size - start, StandardCharsets.UTF_8)).append('\n');
        } catch (IOException error) { text.append("Read error: ").append(error.getMessage()).append('\n'); }
    }
}
