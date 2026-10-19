package io.a10vm.display;

import android.net.LocalSocket;
import java.io.IOException;

public final class DisplaySocket {
    private DisplaySocket() { }

    public static void close(LocalSocket socket) {
        if (socket == null) return;
        // close() alone leaves an in-flight recvmsg alive on Android.
        try { socket.shutdownInput(); } catch (IOException ignored) { }
        try { socket.shutdownOutput(); } catch (IOException ignored) { }
        try { socket.close(); } catch (IOException ignored) { }
    }
}
