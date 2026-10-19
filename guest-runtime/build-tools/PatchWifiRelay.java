import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.reference.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Adapts only the physical Wi-Fi lifecycle and validation callback in stock services.jar. */
public final class PatchWifiRelay {
    private static int gates, callbacks;

    private static Method patch(Method method) {
        boolean gate = method.getDefiningClass().equals("Lcom/android/server/SystemServer;")
                && method.getName().equals("startOtherServices");
        boolean callback = method.getDefiningClass().equals(
                "Lcom/android/server/ConnectivityService$NetworkMonitorCallbacks;")
                && method.getName().equals("notifyNetworkTested");
        if ((!gate && !callback) || method.getImplementation() == null) return method;
        MutableMethodImplementation code = new MutableMethodImplementation(method.getImplementation());
        boolean changed = false;
        for (int i = 0; i < code.getInstructions().size(); i++) {
            Instruction instruction = code.getInstructions().get(i);
            if (!(instruction instanceof ReferenceInstruction)) continue;
            Reference reference = ((ReferenceInstruction) instruction).getReference();
            if (gate && reference instanceof StringReference
                    && ((StringReference) reference).getString().equals("android.hardware.wifi")) {
                int register = ((OneRegisterInstruction) instruction).getRegisterA();
                ImmutableStringReference name = new ImmutableStringReference("io.a10vm.hardware.wifi.physical");
                code.replaceInstruction(i, instruction.getOpcode() == Opcode.CONST_STRING_JUMBO
                        ? new BuilderInstruction31c(Opcode.CONST_STRING_JUMBO, register, name)
                        : new BuilderInstruction21c(Opcode.CONST_STRING, register, name));
                gates++;
                changed = true;
            } else if (callback && reference instanceof FieldReference
                    && ((FieldReference) reference).getName().equals("mNetId")) {
                int netId = ((OneRegisterInstruction) instruction).getRegisterA();
                int result = code.getRegisterCount() - 2;
                if (netId > 15 || result > 15) throw new IllegalStateException("Validation callback registers");
                code.addInstruction(i + 1, new BuilderInstruction35c(Opcode.INVOKE_STATIC,
                        2, result, netId, 0, 0, 0, new ImmutableMethodReference(
                            "Lio/a10vm/guest/GuestConnectivity;", "validationResult",
                            Arrays.asList("I", "I"), "I")));
                code.addInstruction(i + 2, new BuilderInstruction11x(Opcode.MOVE_RESULT, result));
                callbacks++;
                changed = true;
                i += 2;
            }
        }
        return changed ? new ImmutableMethod(method.getDefiningClass(), method.getName(),
                method.getParameters(), method.getReturnType(), method.getAccessFlags(),
                method.getAnnotations(), method.getHiddenApiRestrictions(), code) : method;
    }

    public static void main(String[] args) throws Exception {
        File input = new File(args[0]);
        Path output = Paths.get(args[1]);
        MultiDexContainer<?> container = DexFileFactory.loadDexContainer(input, Opcodes.forApi(29));
        Map<String, byte[]> replaced = new HashMap<>();
        for (String entry : container.getDexEntryNames()) {
            DexFile dex = container.getEntry(entry).getDexFile();
            List<ClassDef> classes = new ArrayList<>();
            int before = gates + callbacks;
            for (ClassDef type : dex.getClasses()) {
                List<Method> methods = new ArrayList<>();
                for (Method method : type.getMethods()) methods.add(patch(method));
                classes.add(new ImmutableClassDef(type.getType(), type.getAccessFlags(),
                        type.getSuperclass(), type.getInterfaces(), type.getSourceFile(),
                        type.getAnnotations(), type.getFields(), methods));
            }
            if (before != gates + callbacks) {
                Path temporary = Files.createTempFile(output.getParent(), "wifi-relay-", ".dex");
                try {
                    DexFileFactory.writeDexFile(temporary.toString(), new ImmutableDexFile(dex.getOpcodes(), classes));
                    DexFileFactory.loadDexFile(temporary.toFile(), Opcodes.forApi(29));
                    replaced.put(entry, Files.readAllBytes(temporary));
                } finally { Files.deleteIfExists(temporary); }
            }
        }
        if (gates != 1 || callbacks != 1) throw new IllegalStateException(
                "Stock Wi-Fi relay anchors: gates=" + gates + " callbacks=" + callbacks);
        try (ZipFile zip = new ZipFile(input); ZipOutputStream stream = new ZipOutputStream(Files.newOutputStream(output))) {
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry source = entries.nextElement();
                ZipEntry destination = new ZipEntry(source.getName());
                destination.setTime(source.getTime());
                stream.putNextEntry(destination);
                byte[] bytes = replaced.get(source.getName());
                if (bytes != null) stream.write(bytes);
                else try (InputStream data = zip.getInputStream(source)) {
                    byte[] buffer = new byte[8192];
                    int count;
                    while ((count = data.read(buffer)) >= 0) stream.write(buffer, 0, count);
                }
                stream.closeEntry();
            }
        }
        System.out.println("wifi_relay_service_gates=" + gates + " validation_callbacks=" + callbacks);
    }
}
