package io.a10vm.guestruntime;

import android.graphics.SurfaceTexture;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.os.Handler;
import java.io.IOException;

/** Drain the host preview consumer so camera callback delivery keeps advancing. */
final class HostCameraPreview implements AutoCloseable {
    private final EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
    private EGLContext context = EGL14.EGL_NO_CONTEXT;
    private EGLSurface surface = EGL14.EGL_NO_SURFACE;
    private int textureId;
    final SurfaceTexture texture;

    HostCameraPreview(Handler handler) throws IOException {
        int[] version = new int[2];
        if (!EGL14.eglInitialize(display, version, 0, version, 1)) throw new IOException("Camera EGL display");
        EGLConfig[] configs = new EGLConfig[1];
        int[] count = new int[1];
        int[] attributes = {EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
                EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE};
        if (!EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) || count[0] == 0)
            throw new IOException("Camera EGL config");
        context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
        surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
        if (!EGL14.eglMakeCurrent(display, surface, surface, context)) {
            EGL14.eglDestroySurface(display, surface); EGL14.eglDestroyContext(display, context);
            throw new IOException("Camera EGL context");
        }
        int[] names = new int[1];
        GLES20.glGenTextures(1, names, 0);
        textureId = names[0];
        texture = new SurfaceTexture(textureId);
        texture.setOnFrameAvailableListener(frame -> {
            EGL14.eglMakeCurrent(display, surface, surface, context);
            frame.updateTexImage();
        }, handler);
    }

    @Override public void close() {
        texture.setOnFrameAvailableListener(null);
        texture.release();
        EGL14.eglMakeCurrent(display, surface, surface, context);
        GLES20.glDeleteTextures(1, new int[] {textureId}, 0);
        EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
        EGL14.eglDestroySurface(display, surface);
        EGL14.eglDestroyContext(display, context);
        EGL14.eglReleaseThread();
    }
}
