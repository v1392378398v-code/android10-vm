package io.a10vm.containerprobe;

import java.io.File;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

final class RuntimeMappings {
    private RuntimeMappings() { }

    static boolean properties(String text, File seed, Set<String> elfPaths, boolean reader, int copies)
            throws Exception {
        Map<String, Integer> counts = new HashMap<>();
        File canonicalSeed = seed.getCanonicalFile();
        for (String line : text.split("\n")) {
            if (!line.startsWith("MAP\t")) continue;
            String[] fields = line.substring(4).trim().split("\\s+", 6);
            if (fields.length != 6 || !fields[5].startsWith("/")) continue;
            File mapped = new File(fields[5]).getCanonicalFile();
            if (elfPaths.contains(mapped.getPath())) continue;
            if (!reader || !canonicalSeed.equals(mapped.getParentFile())
                    || !fields[1].equals("r--s") || Long.parseLong(fields[2], 16) != 0) return false;
            counts.merge(mapped.getName(), 1, Integer::sum);
        }
        if (!reader) return counts.isEmpty();
        return counts.size() == 3 && counts.getOrDefault("property_info", 0) == copies
                && counts.getOrDefault("properties_serial", 0) == copies
                && counts.getOrDefault("a10vm_private_prop", 0) == copies;
    }
}
