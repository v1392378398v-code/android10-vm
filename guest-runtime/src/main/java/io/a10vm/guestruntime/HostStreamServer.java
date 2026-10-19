package io.a10vm.guestruntime;

import android.content.Context;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Process;
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

final class HostStreamServer implements AutoCloseable {
    interface Connection { void serve(LocalSocket socket) throws Exception; }
    private final File path;
    private final Connection connection;
    private final Set<LocalSocket> clients = ConcurrentHashMap.newKeySet();
    private LocalSocket bound;
    private volatile LocalServerSocket server;
    private volatile boolean running;

    HostStreamServer(Context context, String name, Connection connection) throws IOException {
        path = new File(context.getFilesDir().getCanonicalFile(), name + ".sock");
        this.connection = connection;
    }

    synchronized void start() throws IOException {
        if (running) throw new IllegalStateException("Host stream already running");
        if (path.exists() && !path.delete()) throw new IOException("Stale host socket: " + path);
        bound = new LocalSocket();
        bound.bind(new LocalSocketAddress(path.getPath(), LocalSocketAddress.Namespace.FILESYSTEM));
        server = new LocalServerSocket(bound.getFileDescriptor());
        LocalServerSocket endpoint = server;
        running = true;
        Thread accept = new Thread(() -> {
            while (running && server == endpoint) {
                try {
                    LocalSocket socket = endpoint.accept();
                    if (socket.getPeerCredentials().getUid() != Process.myUid() || clients.size() >= 16) {
                        socket.close();
                        continue;
                    }
                    clients.add(socket);
                    Thread client = new Thread(() -> {
                        try (LocalSocket owned = socket) { connection.serve(owned); }
                        catch (Exception error) { if (running) Log.w("A10VM", path.getName(), error); }
                        finally { clients.remove(socket); }
                    }, path.getName() + "-stream");
                    client.setDaemon(true);
                    client.start();
                } catch (IOException error) {
                    if (running && server == endpoint) Log.e("A10VM", path.getName(), error);
                    break;
                }
            }
        }, path.getName() + "-accept");
        accept.setDaemon(true);
        accept.start();
    }

    @Override public synchronized void close() {
        running = false;
        for (LocalSocket socket : clients) try { socket.close(); } catch (IOException ignored) { }
        if (server != null) try { server.close(); } catch (IOException ignored) { }
        if (bound != null) try { bound.close(); } catch (IOException ignored) { }
        server = null;
        bound = null;
        clients.clear();
        path.delete();
    }
}
