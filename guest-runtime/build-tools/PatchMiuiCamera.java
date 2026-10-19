import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.AccessFlags;
import com.android.tools.smali.dexlib2.builder.Label;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.reference.*;
import java.nio.file.*;
import java.util.*;

/** Uses MIUI's ordinary JPEG session when the actual camera reports LEGACY capability. */
public final class PatchMiuiCamera {
    private static final String MODULE = "Lcom/android/camera/module/Camera2Module;";
    private static final String VIDEO = "Lcom/android/camera/module/VideoModule;";
    private static final String LEGACY = "a10vmUsesLegacyCamera";
    private static int sessions, modes, waits, surfaces;

    private static ImmutableMethodReference legacyReference(String module) {
        return new ImmutableMethodReference(module, LEGACY, Collections.emptyList(), "Z");
    }

    private static Method patched(Method method, MutableMethodImplementation code) {
        return new ImmutableMethod(method.getDefiningClass(), method.getName(), method.getParameters(),
                method.getReturnType(), method.getAccessFlags(), method.getAnnotations(),
                method.getHiddenApiRestrictions(), code);
    }

    private static void insert(MutableMethodImplementation code, int index,
            List<com.android.tools.smali.dexlib2.builder.BuilderInstruction> instructions) {
        for (int i = instructions.size() - 1; i >= 0; i--) code.addInstruction(index, instructions.get(i));
    }

    private static Method legacyPredicate(String module, FieldReference capabilities) {
        MutableMethodImplementation code = new MutableMethodImplementation(3);
        code.addInstruction(new BuilderInstruction22c(Opcode.IGET_OBJECT, 0, 2, capabilities));
        code.addInstruction(new BuilderInstruction10x(Opcode.NOP));
        code.addInstruction(new BuilderInstruction35c(Opcode.INVOKE_VIRTUAL, 1, 0, 0, 0, 0, 0,
                new ImmutableMethodReference(capabilities.getType(), "getSupportedHardwareLevel",
                        Collections.emptyList(), "I")));
        code.addInstruction(new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
        code.addInstruction(new BuilderInstruction11n(Opcode.CONST_4, 1, 2));
        code.addInstruction(new BuilderInstruction10x(Opcode.NOP));
        code.addInstruction(new BuilderInstruction11n(Opcode.CONST_4, 0, 1));
        code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 0));
        code.addInstruction(new BuilderInstruction11n(Opcode.CONST_4, 0, 0));
        code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 0));
        Label no = code.newLabelForIndex(8);
        code.replaceInstruction(1, new BuilderInstruction21t(Opcode.IF_EQZ, 0, no));
        code.replaceInstruction(5, new BuilderInstruction22t(Opcode.IF_NE, 0, 1, no));
        return new ImmutableMethod(module, LEGACY, Collections.emptyList(), "Z",
                AccessFlags.PRIVATE.getValue() | AccessFlags.SYNTHETIC.getValue(),
                Collections.emptySet(), Collections.emptySet(), code);
    }

    private static Method patch(Method method) {
        String module = method.getDefiningClass();
        if (module.equals(VIDEO) && !method.getName().equals("getOperatingMode")) return method;
        boolean session = method.getName().equals("isParallelSessionEnable") && method.getReturnType().equals("Z");
        boolean mode = method.getName().equals("getOperatingMode") && method.getReturnType().equals("I");
        boolean start = method.getName().equals("startPreview") && method.getReturnType().equals("V");
        boolean surface = method.getName().equals("updatePreviewSurface") && method.getReturnType().equals("V");
        if (!session && !mode && !start && !surface) return method;
        if (method.getImplementation() == null || !method.getParameters().isEmpty())
            throw new IllegalStateException("Camera session method changed");
        int existing = 0;
        for (Instruction instruction : method.getImplementation().getInstructions()) {
            if (!(instruction instanceof ReferenceInstruction)) continue;
            Reference reference = ((ReferenceInstruction) instruction).getReference();
            if (reference instanceof MethodReference && ((MethodReference) reference).getName().equals(LEGACY) &&
                    ((MethodReference) reference).getDefiningClass().equals(module)) existing++;
        }
        if (existing > 1) throw new IllegalStateException("Camera guard duplicated: " + method.getName());
        if (existing == 1) {
            if (session) sessions++; else if (mode) modes++; else if (start) waits++; else surfaces++;
            return method;
        }
        MutableMethodImplementation code = new MutableMethodImplementation(method.getImplementation());
        int receiver = code.getRegisterCount() - 1;
        if (receiver < 2 || receiver > 15) throw new IllegalStateException("Camera session registers changed");
        if (start || surface) {
            int anchors = 0;
            for (int i = 0; i < code.getInstructions().size(); i++) {
                Instruction instruction = code.getInstructions().get(i);
                if (instruction.getOpcode() == Opcode.MONITOR_ENTER)
                    throw new IllegalStateException("Camera surface guard must precede device locking");
                if (!(instruction instanceof ReferenceInstruction)) continue;
                Reference reference = ((ReferenceInstruction) instruction).getReference();
                if (!(reference instanceof MethodReference) ||
                        !((MethodReference) reference).getName().equals("getSurfaceTexture")) continue;
                Instruction result = code.getInstructions().get(i + 1);
                Instruction next = code.getInstructions().get(i + 2);
                if (result.getOpcode() != Opcode.MOVE_RESULT_OBJECT || next.getOpcode() != Opcode.SGET_OBJECT)
                    throw new IllegalStateException("Camera surface lifetime anchor changed");
                int texture = ((OneRegisterInstruction) result).getRegisterA();
                int scratch = ((OneRegisterInstruction) next).getRegisterA();
                if (texture == scratch) throw new IllegalStateException("Camera surface scratch overlaps");
                int at = i + 2;
                Label original = code.newLabelForIndex(at);
                List<com.android.tools.smali.dexlib2.builder.BuilderInstruction> guard = new ArrayList<>();
                if (start) guard.add(new BuilderInstruction21t(Opcode.IF_NEZ, texture, original));
                guard.add(new BuilderInstruction35c(Opcode.INVOKE_DIRECT, 1, receiver, 0, 0, 0, 0, legacyReference(module)));
                guard.add(new BuilderInstruction11x(Opcode.MOVE_RESULT, scratch));
                guard.add(new BuilderInstruction21t(Opcode.IF_EQZ, scratch, original));
                if (surface) {
                    guard.add(new BuilderInstruction10x(Opcode.NOP));
                    guard.add(new BuilderInstruction35c(Opcode.INVOKE_VIRTUAL, 1, receiver, 0, 0, 0, 0,
                            new ImmutableMethodReference(MODULE, "startPreview", Collections.emptyList(), "V")));
                }
                guard.add(new BuilderInstruction10x(Opcode.RETURN_VOID));
                insert(code, at, guard);
                if (surface) code.replaceInstruction(at + 3,
                        new BuilderInstruction21t(Opcode.IF_EQZ, texture, code.newLabelForIndex(at + 5)));
                anchors++;
                break;
            }
            if (anchors != 1) throw new IllegalStateException("Camera surface anchor missing: " + method.getName());
            if (start) waits++; else surfaces++;
            return patched(method, code);
        }
        Label original = code.newLabelForIndex(0);
        List<com.android.tools.smali.dexlib2.builder.BuilderInstruction> guard = Arrays.asList(
            new BuilderInstruction35c(Opcode.INVOKE_DIRECT, 1, receiver, 0, 0, 0, 0, legacyReference(module)),
            new BuilderInstruction11x(Opcode.MOVE_RESULT, 0),
            new BuilderInstruction21t(Opcode.IF_EQZ, 0, original),
            new BuilderInstruction11n(Opcode.CONST_4, 0, 0),
            new BuilderInstruction11x(Opcode.RETURN, 0));
        // Insert backwards so the original label stays on the unchanged entry instruction.
        insert(code, 0, guard);
        if (session) sessions++; else modes++;
        return patched(method, code);
    }

    public static void main(String[] args) throws Exception {
        DexArchive.rewrite(Paths.get(args[0]), Paths.get(args[1]), dex -> {
            List<ClassDef> classes = new ArrayList<>();
            boolean changed = false;
            for (ClassDef type : dex.getClasses()) {
                if (!type.getType().equals(MODULE) && !type.getType().equals(VIDEO)) {
                    classes.add(type);
                    continue;
                }
                type = ImmutableClassDef.of(type);
                FieldReference capabilities = null;
                boolean adapted = false;
                for (Method method : type.getMethods()) {
                    if (method.getName().equals(LEGACY)) adapted = true;
                    if (!method.getName().equals("getOperatingMode") || method.getImplementation() == null) continue;
                    for (Instruction instruction : method.getImplementation().getInstructions()) {
                        if (!(instruction instanceof ReferenceInstruction)) continue;
                        Reference reference = ((ReferenceInstruction) instruction).getReference();
                        if (reference instanceof FieldReference && ((FieldReference) reference).getName()
                                .equals("mCameraCapabilities")) capabilities = (FieldReference) reference;
                    }
                }
                if (capabilities == null || !capabilities.getType().equals("Lcom/android/camera2/CameraCapabilities;"))
                    throw new IllegalStateException("MIUI camera capability anchor missing");
                List<Method> methods = new ArrayList<>();
                for (Method method : type.getMethods()) methods.add(patch(method));
                if (!adapted) methods.add(legacyPredicate(type.getType(), capabilities));
                classes.add(new ImmutableClassDef(type.getType(), type.getAccessFlags(), type.getSuperclass(),
                        type.getInterfaces(), type.getSourceFile(), type.getAnnotations(), type.getFields(), methods));
                changed = true;
            }
            return changed ? new ImmutableDexFile(dex.getOpcodes(), classes) : dex;
        }, () -> {
            if (sessions != 1 || modes != 2 || waits != 1 || surfaces != 1)
                throw new IllegalStateException("MIUI camera guard anchors: " + sessions + "/" + modes +
                        "/" + waits + "/" + surfaces);
        });
        System.out.println("camera_legacy_session_guards=" + sessions + " camera_legacy_mode_guards=" + modes +
                " camera_surface_wait_guards=" + waits + " camera_surface_start_guards=" + surfaces);
    }
}
