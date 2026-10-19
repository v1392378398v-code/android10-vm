package com.hooker.lsplant;

import java.lang.reflect.Method;

public final class HookMain {
    public static native boolean nPrepareNativeCapture();
    public static native boolean nInit();

    public static int compute(int value) {
        return value + 1;
    }

    public static void main(String[] args) throws Exception {
        System.load(args[0]);
        boolean capture = nPrepareNativeCapture();
        System.out.println("lsplant_native_capture=" + (capture ? 1 : 0));
        boolean initialized = capture && nInit();
        System.out.println("lsplant_initialized=" + (initialized ? 1 : 0));
        if (!initialized) throw new AssertionError("LSPlant initialization failed");
        Method target = HookMain.class.getMethod("compute", int.class);
        Hooker hooker = new Hooker();
        if (!Integer.valueOf(2).equals(target.invoke(null, 1))) throw new AssertionError("Original method");
        Method backup = hooker.doHook(target, Hooker.class.getMethod("callback", Object[].class));
        boolean hooked = backup != null && Integer.valueOf(42).equals(target.invoke(null, 1));
        System.out.println("lsplant_method_hooked=" + (hooked ? 1 : 0));
        if (!hooked) throw new AssertionError("Hook callback not invoked");
        boolean original = Integer.valueOf(2).equals(backup.invoke(null, 1));
        System.out.println("lsplant_backup_callable=" + (original ? 1 : 0));
        if (!original) throw new AssertionError("Hook backup method");
        boolean restored = hooker.doUnhook(target) && Integer.valueOf(2).equals(target.invoke(null, 1));
        System.out.println("lsplant_method_restored=" + (restored ? 1 : 0));
        if (!restored) throw new AssertionError("Unhook method");
    }
}
