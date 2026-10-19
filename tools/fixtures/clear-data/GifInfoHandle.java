package com.tencent.libra.extension.gif;

import android.graphics.Bitmap;

/** JNI declarations used to exercise the installed QQ decoder without account data. */
public final class GifInfoHandle {
    static { System.loadLibrary("giflibra"); }
    public static native long openByteArray(byte[] bytes);
    public static native int getWidth(long handle);
    public static native int getHeight(long handle);
    public static native long renderFrame(long handle, Bitmap bitmap);
    public static native void free(long handle);
}
