package io.a10vm.guestruntime;

import android.content.Context;
import android.net.LocalSocket;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;

/** Uses the app's own host vibrator access; the guest keeps its framework permission checks. */
public final class HostVibratorBridge implements AutoCloseable {
    public static final String HAL_NAME = "android.hardware.vibrator";
    private final Vibrator vibrator;
    private final HostStreamServer server;
    private int amplitude = VibrationEffect.DEFAULT_AMPLITUDE;
    private long deadline;

    public HostVibratorBridge(Context context) throws IOException {
        vibrator = context.getSystemService(Vibrator.class);
        server = new HostStreamServer(context, "vibrator", this::serve);
    }

    public boolean available() { return vibrator != null && vibrator.hasVibrator(); }
    public void start() throws IOException { server.start(); }

    private synchronized void serve(LocalSocket socket) throws Exception {
        socket.setSoTimeout(3000);
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x41313056 || input.readInt() != 1) throw new IOException("Vibrator protocol");
        int command = input.readInt(), result = 0;
        switch (command) {
            case 1: result = available() ? 1 : 0; break;
            case 2: result = available() && vibrator.hasAmplitudeControl() ? 1 : 0; break;
            case 3:
                long millis = input.readInt() & 0xffffffffL;
                if (!available()) result = -19;
                else if (millis == 0) result = -22;
                else {
                    deadline = SystemClock.elapsedRealtime() + millis;
                    vibrator.vibrate(VibrationEffect.createOneShot(millis, amplitude));
                }
                break;
            case 4:
                if (vibrator != null) vibrator.cancel(); deadline = 0; break;
            case 5:
                int value = input.readInt();
                if (value < 1 || value > 255) result = -22;
                else if (!available() || !vibrator.hasAmplitudeControl()) result = -38;
                else {
                    amplitude = value;
                    long remaining = deadline - SystemClock.elapsedRealtime();
                    if (remaining > 0) vibrator.vibrate(VibrationEffect.createOneShot(remaining, amplitude));
                }
                break;
            default: result = -22;
        }
        output.writeInt(result); output.flush();
    }

    @Override public synchronized void close() {
        server.close();
        if (vibrator != null) vibrator.cancel();
        deadline = 0; amplitude = VibrationEffect.DEFAULT_AMPLITUDE;
    }
}
