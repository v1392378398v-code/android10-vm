package io.a10vm.guest;

import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicReference;

/** Exercise the LMKD priority packet against an actual disposable child process. */
public final class GuestMemoryPriorityCheck {
    public static void main(String[] args) throws Exception {
        File path = new File(args[0], "memory-priority.sock");
        path.delete();
        LocalSocket listener = new LocalSocket(LocalSocket.SOCKET_SEQPACKET);
        listener.bind(new LocalSocketAddress(path.getPath(), LocalSocketAddress.Namespace.FILESYSTEM));
        Process child = new ProcessBuilder("/system/bin/sleep", "60").start();
        Field pidField = child.getClass().getDeclaredField("pid");
        pidField.setAccessible(true);
        int pid = ((Number) pidField.get(child)).intValue();
        AtomicReference<Throwable> fault = new AtomicReference<>();
        try (LocalSocket held = listener;
                LocalServerSocket server = new LocalServerSocket(listener.getFileDescriptor());
                LocalSocket client = new LocalSocket(LocalSocket.SOCKET_SEQPACKET)) {
            GuestMemory memory = new GuestMemory();
            Method commands = GuestMemory.class.getDeclaredMethod("commands", LocalSocket.class);
            commands.setAccessible(true);
            Thread worker = new Thread(() -> {
                try { commands.invoke(memory, server.accept()); }
                catch (Throwable error) { fault.set(error); }
            });
            worker.setDaemon(true);
            worker.start();
            client.connect(new LocalSocketAddress(path.getPath(), LocalSocketAddress.Namespace.FILESYSTEM));
            priority(client, pid, 10042, 950);
            expect(pid, 950, fault);
            System.out.println("memory_cached_kernel_adj=950");
            priority(client, pid, 10042, 0);
            expect(pid, 0, fault);
            priority(client, pid, 10042, -800);
            expect(pid, 0, fault);
            System.out.println("memory_foreground_kernel_adj=0");
            priority(client, pid, 1000, 950);
            Thread.sleep(100);
            expect(pid, 0, fault);
            System.out.println("memory_system_uid_ignored=1");
            client.getOutputStream().write(ByteBuffer.allocate(8).putInt(2).putInt(pid).array());
            client.getOutputStream().flush();
            System.out.println("memory_priority_ready=1");
        } finally {
            child.destroyForcibly();
            child.waitFor();
            path.delete();
        }
    }

    private static void priority(LocalSocket client, int pid, int uid, int adjustment) throws Exception {
        client.getOutputStream().write(ByteBuffer.allocate(16)
                .putInt(1).putInt(pid).putInt(uid).putInt(adjustment).array());
        client.getOutputStream().flush();
    }

    private static void expect(int pid, int expected, AtomicReference<Throwable> fault) throws Exception {
        long deadline = System.nanoTime() + 3000000000L;
        int actual;
        do {
            if (fault.get() != null) throw new AssertionError("LMKD receiver failed", fault.get());
            actual = Integer.parseInt(ProcessEvidence.read("/proc/" + pid + "/oom_score_adj").trim());
            if (actual == expected) return;
            Thread.sleep(10);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("LMKD kernel priority: expected=" + expected + " actual=" + actual);
    }
}
