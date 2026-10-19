package io.a10vm.fixture.cleardata;

import android.app.Activity;
import android.content.Context;
import android.os.Bundle;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;

public final class DataActivity extends Activity {
    private static void marker(File directory) throws Exception {
        if (directory == null) throw new Exception("Application storage directory missing");
        File nested = new File(directory, "clear-probe/nested");
        if (!nested.isDirectory() && !nested.mkdirs()) throw new Exception("mkdir: " + nested);
        try (FileOutputStream output = new FileOutputStream(new File(nested, "marker"))) {
            output.write(1);
        }
    }

    private void largeMarker(File directory) throws Exception {
        File path = new File(directory, "clear-probe/nested/marker");
        try (InputStream input = getAssets().open("lifecycle-padding.bin");
                FileOutputStream output = new FileOutputStream(path)) {
            byte[] chunk = new byte[1024 * 1024];
            int count;
            while ((count = input.read(chunk)) != -1) output.write(chunk, 0, count);
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            if (getIntent().getBooleanExtra("keystore", false)) KeyProbe.verify(this);
            if (getIntent().getBooleanExtra("gif", false)) {
                byte[] gif = android.util.Base64.decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", 0);
                long handle = com.tencent.libra.extension.gif.GifInfoHandle.openByteArray(gif);
                if (handle == 0) throw new Exception("GIF handle missing");
                try {
                    if (com.tencent.libra.extension.gif.GifInfoHandle.getWidth(handle) != 1 ||
                            com.tencent.libra.extension.gif.GifInfoHandle.getHeight(handle) != 1)
                        throw new Exception("GIF dimensions changed");
                    android.graphics.Bitmap frame = android.graphics.Bitmap.createBitmap(1, 1,
                            android.graphics.Bitmap.Config.ARGB_8888);
                    com.tencent.libra.extension.gif.GifInfoHandle.renderFrame(handle, frame);
                    android.util.Log.i("A10VM-GifFixture", "rendered pixel=" + frame.getPixel(0, 0));
                    frame.recycle();
                } finally { com.tencent.libra.extension.gif.GifInfoHandle.free(handle); }
            }
            Context de = createDeviceProtectedStorageContext();
            int starts = getSharedPreferences("probe", 0).getInt("starts", 0) + 1;
            if (!getSharedPreferences("probe", 0).edit().putInt("starts", starts).commit())
                throw new Exception("preferences commit");
            marker(getFilesDir());
            marker(getCacheDir());
            marker(getCodeCacheDir());
            marker(de.getFilesDir());
            marker(de.getCacheDir());
            marker(getExternalFilesDir(null));
            marker(getExternalCacheDir());
            for (String alias : new String[] {"/sdcard", "/storage/self/primary", "/mnt/user/0/primary",
                    "/mnt/runtime/default/emulated/0", "/mnt/runtime/read/emulated/0",
                    "/mnt/runtime/write/emulated/0", "/mnt/runtime/full/emulated/0"}) {
                if (!new File(alias + "/Android/data/" + getPackageName() + "/files/clear-probe/nested/marker").isFile())
                    throw new Exception("External storage alias missing: " + alias);
            }
            if (getIntent().getBooleanExtra("large", false)) {
                largeMarker(getFilesDir());
                largeMarker(de.getFilesDir());
            }
            TextView text = new TextView(this);
            text.setText("Data clear fixture: starts=" + starts);
            setContentView(text);
            android.util.Log.i("A10VM-ClearFixture", "ready starts=" + starts);
        } catch (Exception failure) {
            throw new IllegalStateException("Clear-data fixture setup", failure);
        }
    }
}
