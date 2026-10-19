package io.a10vm.framework;

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.os.Parcel;
import java.lang.reflect.Field;

/** Adapts successful Java package-query replies without changing framework objects. */
public final class PackageQueryReplies {
    private static final int APPLICATION = transaction("getApplicationInfo");
    private static final int PACKAGE = transaction("getPackageInfo");
    private static final int VERSIONED_PACKAGE = transaction("getPackageInfoVersioned");

    private PackageQueryReplies() {}

    public static boolean adaptForCaller(int code, Parcel output, boolean handled, int callerUid) {
        if (!handled || output == null ||
                (code != APPLICATION && code != PACKAGE && code != VERSIONED_PACKAGE)) return handled;
        // System queries also supply bindApplication and must retain guest namespace paths.
        if (!android.os.Process.isApplicationUid(callerUid)) return handled;
        Parcel input = Parcel.obtain();
        try {
            input.appendFrom(output, 0, output.dataSize());
            input.setDataPosition(0);
            int exception = input.readInt();
            if (exception == -128) {
                int position = input.dataPosition();
                int size = input.readInt();
                if (size < 4 || position + size > input.dataSize())
                    throw new IllegalArgumentException("Invalid package-query reply header");
                input.setDataPosition(position + size);
            } else if (exception != 0) return handled;
            int prefix = input.dataPosition();
            if (input.readInt() == 0) return handled;
            android.os.Parcelable value = code == APPLICATION
                    ? PackageCodePaths.reply(ApplicationInfo.CREATOR.createFromParcel(input))
                    : PackageCodePaths.reply(PackageInfo.CREATOR.createFromParcel(input));
            output.setDataSize(0);
            output.setDataPosition(0);
            // Preserve the exact exception/StrictMode header and its client-side handling.
            output.appendFrom(input, 0, prefix);
            output.writeInt(1);
            value.writeToParcel(output, android.os.Parcelable.PARCELABLE_WRITE_RETURN_VALUE);
            return handled;
        } finally { input.recycle(); }
    }

    private static int transaction(String name) {
        try {
            Field field = Class.forName("android.content.pm.IPackageManager$Stub")
                    .getDeclaredField("TRANSACTION_" + name);
            field.setAccessible(true);
            return field.getInt(null);
        } catch (ReflectiveOperationException error) {
            throw new IllegalStateException("Package query transaction missing: " + name, error);
        }
    }
}
