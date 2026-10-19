package io.a10vm.guestruntime;

import android.content.Context;
import android.net.LocalSocket;
import android.os.Parcel;
import android.os.ParcelFileDescriptor;
import android.os.SharedMemory;
import android.system.ErrnoException;
import android.system.OsConstants;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.FileDescriptor;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** Use the host's public shared memory API when the guest's memfd seals are absent. */
public final class HostSharedMemoryBridge implements AutoCloseable {
    private final HostStreamServer server;

    public HostSharedMemoryBridge(Context context) throws IOException {
        server = new HostStreamServer(context, "shared-memory", this::serve);
    }

    public void start() throws IOException { server.start(); }

    private void serve(LocalSocket socket) throws Exception {
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x4131304d || input.readInt() != 1 || input.readInt() != 1)
            throw new IOException("Shared memory protocol");
        int size = input.readInt();
        int length = input.readInt();
        if (size <= 0 || length < 0 || length > 255) { output.writeInt(-OsConstants.EINVAL); return; }
        byte[] name = new byte[length];
        input.readFully(name);
        try (SharedMemory memory = SharedMemory.create(new String(name, StandardCharsets.UTF_8), size)) {
            Parcel parcel = Parcel.obtain();
            try {
                memory.writeToParcel(parcel, 0);
                parcel.setDataPosition(0);
                try (ParcelFileDescriptor descriptor = parcel.readFileDescriptor()) {
                    if (descriptor == null) throw new IOException("Shared memory descriptor missing");
                    socket.setFileDescriptorsForSend(new FileDescriptor[]{descriptor.getFileDescriptor()});
                    output.write(new byte[4]);
                    output.flush();
                    socket.setFileDescriptorsForSend(null);
                }
            } finally { parcel.recycle(); }
        } catch (ErrnoException error) { output.writeInt(-error.errno); }
    }

    @Override public void close() { server.close(); }
}
