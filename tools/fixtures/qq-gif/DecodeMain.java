package io.a10vm.fixture.gif;

import android.graphics.Bitmap;
import com.tencent.libra.extension.gif.GifInfoHandle;

public final class DecodeMain {
    public static void main(String[] args) throws Exception {
        byte[] gif = android.util.Base64.decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", 0);
        System.out.println("gif_decode_open=1");
        long handle = GifInfoHandle.openByteArray(gif);
        if (handle == 0) throw new AssertionError("GIF handle missing");
        try {
            if (GifInfoHandle.getWidth(handle) != 1 || GifInfoHandle.getHeight(handle) != 1)
                throw new AssertionError("GIF dimensions changed");
            System.out.println("gif_decode_dimensions=1x1");
            Bitmap bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888);
            System.out.println("gif_decode_render=1");
            GifInfoHandle.renderFrame(handle, bitmap);
            System.out.println("gif_decode_pixel=" + bitmap.getPixel(0, 0));
            bitmap.recycle();
        } finally { GifInfoHandle.free(handle); }
        System.out.println("gif_decode_complete=1");
    }
}
