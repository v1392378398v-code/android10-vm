package io.a10vm.guest;

import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.os.IBinder;
import android.os.SystemClock;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

public final class RomDesktopCheck {
    public static void main(String[] args) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + Long.parseLong(args[0]);
        Method service = Class.forName("android.os.ServiceManager").getMethod("checkService", String.class);
        Method property = Class.forName("android.os.SystemProperties").getMethod("get", String.class);
        Method isUnlocked = Class.forName("android.os.IUserManager").getMethod("isUserUnlocked", int.class);
        Method resolve = Class.forName("android.content.pm.IPackageManager").getMethod(
                "resolveIntent", Intent.class, String.class, int.class, int.class);
        String[] names = {"activity", "activity_task", "package", "user", "window", "display", "power"};
        String boot = "", home = "none";
        ResolveInfo resolved = null;
        Object packages = null;
        boolean ready = false;
        boolean unlocked = false;
        Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
        do {
            ready = true;
            for (String name : names) {
                IBinder binder = (IBinder) service.invoke(null, name);
                ready &= binder != null && binder.isBinderAlive();
            }
            boot = (String) property.invoke(null, "sys.boot_completed");
            if (ready && "1".equals(boot)) {
                Object user = Class.forName("android.os.IUserManager$Stub")
                        .getMethod("asInterface", IBinder.class).invoke(null, service.invoke(null, "user"));
                unlocked = (Boolean) isUnlocked.invoke(user, 0);
                packages = Class.forName("android.content.pm.IPackageManager$Stub")
                        .getMethod("asInterface", IBinder.class).invoke(null, service.invoke(null, "package"));
                resolved = (ResolveInfo) resolve.invoke(packages, intent, null, 0, 0);
                if (unlocked && resolved != null) {
                    home = resolved.activityInfo.packageName;
                    break;
                }
            }
            SystemClock.sleep(100);
        } while (SystemClock.elapsedRealtime() < deadline);
        for (String name : names) {
            IBinder binder = (IBinder) service.invoke(null, name);
            System.out.println("rom_service_" + name + "=" + (binder != null && binder.isBinderAlive() ? 1 : 0));
        }
        System.out.println("rom_boot_completed=" + boot);
        System.out.println("rom_user_unlocked=" + unlocked);
        System.out.println("rom_product_device=" + property.invoke(null, "ro.product.device"));
        System.out.println("rom_product_model=" + property.invoke(null, "ro.product.model"));
        if (!ready || !"1".equals(boot) || !unlocked || resolved == null)
            throw new AssertionError("ROM desktop boot has not completed");
        Method show = Class.forName("io.a10vm.guest.DesktopHome").getDeclaredMethod("show", IBinder.class, ResolveInfo.class);
        show.setAccessible(true);
        do {
            System.out.println("rom_home_candidate=" + home);
            try {
                show.invoke(null, service.invoke(null, "activity_task"), resolved);
                break;
            } catch (InvocationTargetException failure) {
                ResolveInfo next = (ResolveInfo) resolve.invoke(packages, intent, null, 0, 0);
                if (!(failure.getCause() instanceof AssertionError) || next == null ||
                        (next.activityInfo.packageName.equals(resolved.activityInfo.packageName) &&
                         next.activityInfo.name.equals(resolved.activityInfo.name)) ||
                        SystemClock.elapsedRealtime() >= deadline) throw failure;
                resolved = next;
                home = next.activityInfo.packageName;
            }
        } while (true);
        System.out.println("rom_home_package=" + home);
        ((IBinder) service.invoke(null, "window")).dump(java.io.FileDescriptor.out, new String[]{"windows"});
        System.out.println("rom_desktop_ready=1");
    }
}
