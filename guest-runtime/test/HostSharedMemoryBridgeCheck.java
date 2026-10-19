package io.a10vm.guestruntime;

import android.content.ContextWrapper;
import java.io.File;
import java.util.Arrays;

/** Exercise the real public SDK bridge with the native guest client. */
public final class HostSharedMemoryBridgeCheck {
    public static void main(String[] args) throws Exception {
        File directory = new File(args[0]);
        ContextWrapper context = new ContextWrapper(null) {
            @Override public File getFilesDir() { return directory; }
        };
        try (HostSharedMemoryBridge bridge = new HostSharedMemoryBridge(context)) {
            bridge.start();
            System.out.println("host_bridge_uid=" + android.os.Process.myUid());
            Process check = new ProcessBuilder(Arrays.copyOfRange(args, 1, args.length)).inheritIO().start();
            if (check.waitFor() != 0) throw new AssertionError("Native shared memory bridge check failed");
            System.out.println("host_shared_memory_bridge=passed");
        }
        System.exit(0);
    }
}
