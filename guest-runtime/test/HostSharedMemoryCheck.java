package io.a10vm.guestruntime;

import android.os.Parcel;
import android.os.ParcelFileDescriptor;
import android.os.SharedMemory;
import android.system.Os;
import android.system.OsConstants;
import java.nio.ByteBuffer;

public final class HostSharedMemoryCheck {
    public static void main(String[] args) throws Exception {
        try (SharedMemory memory = SharedMemory.create("a10vm-host-memory-check", 4096)) {
            ByteBuffer bytes = memory.mapReadWrite();
            bytes.putInt(0, 0x4131304d);
            Parcel parcel = Parcel.obtain();
            try {
                memory.writeToParcel(parcel, 0);
                parcel.setDataPosition(0);
                try (ParcelFileDescriptor fd = parcel.readFileDescriptor()) {
                    if (fd == null) throw new AssertionError("Shared memory descriptor missing");
                    System.out.println("host_memory_fd=" + Os.readlink("/proc/self/fd/" + fd.getFd()));
                }
            } finally { parcel.recycle(); }
            if (!memory.setProtect(OsConstants.PROT_READ)) throw new AssertionError("Read protection rejected");
            if (bytes.getInt(0) != 0x4131304d) throw new AssertionError("Shared memory round trip");
            SharedMemory.unmap(bytes);
            System.out.println("host_shared_memory=passed");
        }
        System.exit(0);
    }
}
