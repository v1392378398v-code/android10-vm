import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.iface.DexFile;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

final class DexArchive {
    interface Transform { DexFile apply(DexFile dex) throws Exception; }

    static void rewrite(Path input, Path output, Transform transform, Runnable verify) throws Exception {
        if (input.toRealPath().equals(output.toAbsolutePath().normalize()))
            throw new IllegalArgumentException("Preserve the original archive");
        Files.createDirectories(output.toAbsolutePath().getParent());
        Map<String, byte[]> replacements = new HashMap<>();
        com.android.tools.smali.dexlib2.iface.MultiDexContainer<?> container =
                DexFileFactory.loadDexContainer(input.toFile(), Opcodes.forApi(29));
        for (String name : container.getDexEntryNames()) {
            DexFile source = container.getEntry(name).getDexFile();
            DexFile changed = transform.apply(source);
            if (changed == source) continue;
            Path temporary = Files.createTempFile(output.toAbsolutePath().getParent(), "dex-adapter-", ".dex");
            try {
                DexFileFactory.writeDexFile(temporary.toString(), changed);
                DexFileFactory.loadDexFile(temporary.toFile(), Opcodes.forApi(29));
                replacements.put(name, Files.readAllBytes(temporary));
            } finally { Files.deleteIfExists(temporary); }
        }
        verify.run();
        try (ZipFile zip = new ZipFile(input.toFile());
                ZipOutputStream stream = new ZipOutputStream(Files.newOutputStream(output))) {
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry source = entries.nextElement();
                ZipEntry destination = new ZipEntry(source.getName());
                destination.setTime(source.getTime());
                stream.putNextEntry(destination);
                byte[] replacement = replacements.get(source.getName());
                if (replacement != null) stream.write(replacement);
                else try (InputStream data = zip.getInputStream(source)) {
                    byte[] buffer = new byte[8192];
                    int count;
                    while ((count = data.read(buffer)) >= 0) stream.write(buffer, 0, count);
                }
                stream.closeEntry();
            }
        }
        try (ZipFile source = new ZipFile(input.toFile()); ZipFile derived = new ZipFile(output.toFile())) {
            if (source.size() != derived.size()) throw new AssertionError("Archive entry count changed");
            Enumeration<? extends ZipEntry> entries = source.entries();
            while (entries.hasMoreElements()) {
                String name = entries.nextElement().getName();
                if (!replacements.containsKey(name) && !Arrays.equals(
                        bytes(source, name), bytes(derived, name)))
                    throw new AssertionError("Non-target entry changed: " + name);
            }
        }
    }

    private static byte[] bytes(ZipFile zip, String name) throws IOException {
        try (InputStream input = zip.getInputStream(zip.getEntry(name));
                ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) >= 0) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }
}
