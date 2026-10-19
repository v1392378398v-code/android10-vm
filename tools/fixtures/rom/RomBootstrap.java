package io.a10vm.guest;

public final class RomBootstrap {
    public static void main(String[] args) throws Throwable {
        BootNativeLibraries.load();
        try {
            Class.forName("io.a10vm.guest.DesktopBoot").getMethod("main", String[].class)
                    .invoke(null, (Object) args);
        } catch (java.lang.reflect.InvocationTargetException error) {
            throw error.getCause();
        }
    }
}
