package io.a10vm.guest;

public final class RomHardwareCheck {
    public static void main(String[] args) throws Exception {
        Object manager = Class.forName("android.hidl.manager.V1_0.IServiceManager")
                .getMethod("getService").invoke(null);
        if (manager == null) throw new AssertionError("HwBinder service manager missing");
        System.out.println("rom_hardware_ready=1");
    }
}
