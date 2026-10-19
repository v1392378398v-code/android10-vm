package io.a10vm.guestruntime;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;
import java.util.Set;

final class GuestMappingPaths {
    static String resolve(File root, String mapping, Set<String> allowed) throws IOException {
        Path base = root.toPath();
        Path resolved = base;
        Deque<String> pending = new ArrayDeque<>(Arrays.asList(mapping.split("/")));
        int links = 0;
        while (!pending.isEmpty()) {
            String component = pending.removeFirst();
            if (component.isEmpty() || component.equals(".")) continue;
            if (component.equals("..")) {
                if (!resolved.equals(base)) resolved = resolved.getParent();
                continue;
            }
            resolved = resolved.resolve(component);
            if (!Files.isSymbolicLink(resolved)) continue;
            if (++links > 40) throw new IOException("Guest mapping symlink loop: " + mapping);
            Path target = Files.readSymbolicLink(resolved);
            if (target.isAbsolute()) {
                // Packaged native aliases point outside rootfs into nativeLibraryDir.
                Path physical = target;
                for (String part : pending) physical = physical.resolve(part);
                String canonical = physical.toFile().getCanonicalPath();
                if (allowed.contains(canonical)) return canonical;
            }
            resolved = target.isAbsolute() ? base : resolved.getParent();
            String[] parts = target.toString().split("/");
            for (int i = parts.length - 1; i >= 0; --i) pending.addFirst(parts[i]);
        }
        return resolved.toFile().getCanonicalPath();
    }
}
