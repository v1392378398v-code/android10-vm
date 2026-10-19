package io.a10vm.framework;

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.os.Parcel;

/** Maps only the APK paths serialized by package-query Binder replies. */
public final class PackageCodePaths {
    private PackageCodePaths() {}

    public static ApplicationInfo reply(ApplicationInfo source) {
        if (source == null) return null;
        ApplicationInfo result = new ApplicationInfo(source);
        result.sourceDir = physical(source.sourceDir);
        result.publicSourceDir = physical(source.publicSourceDir);
        result.splitSourceDirs = physical(source.splitSourceDirs);
        result.splitPublicSourceDirs = physical(source.splitPublicSourceDirs);
        return result;
    }

    public static PackageInfo reply(PackageInfo source) {
        if (source == null) return null;
        Parcel parcel = Parcel.obtain();
        try {
            source.writeToParcel(parcel, 0);
            parcel.setDataPosition(0);
            PackageInfo result = PackageInfo.CREATOR.createFromParcel(parcel);
            result.applicationInfo = reply(result.applicationInfo);
            return result;
        } finally { parcel.recycle(); }
    }

    private static String[] physical(String[] paths) {
        if (paths == null) return null;
        String[] result = paths.clone();
        for (int i = 0; i < result.length; i++) result[i] = physical(result[i]);
        return result;
    }

    private static String physical(String path) {
        String root = System.getenv("A10VM_ROOTFS");
        if (path == null || root == null || root.isEmpty() || beneath(path, root) ||
                beneath(path, System.getenv("A10VM_HOST_ROOT")) ||
                beneath(path, System.getenv("A10VM_STATE_ROOT"))) return path;
        // System APK paths also define linker namespace permissions in guest coordinates.
        return beneath(path, "/data/app") || beneath(path, "/mnt/expand") ? root + path : path;
    }

    private static boolean beneath(String path, String directory) {
        return directory != null && !directory.isEmpty() &&
                (path.equals(directory) || path.startsWith(directory + "/"));
    }
}
