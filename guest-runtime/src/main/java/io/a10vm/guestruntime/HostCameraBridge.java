package io.a10vm.guestruntime;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.hardware.Camera;
import android.net.LocalSocket;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** Public host camera APIs behind the guest's private camera transport. */
@SuppressWarnings("deprecation")
public final class HostCameraBridge implements AutoCloseable {
    private final Context context;
    private final HostStreamServer server;
    private final AtomicInteger nextId = new AtomicInteger();
    private final Map<Integer, HostCameraSession> sessions = new ConcurrentHashMap<>();

    public HostCameraBridge(Context context) throws IOException {
        this.context = context.getApplicationContext();
        server = new HostStreamServer(context, "camera", this::serve);
    }

    public void start() throws IOException {
        org.json.JSONArray cameras = new org.json.JSONArray();
        for (int id = 0; id < Camera.getNumberOfCameras(); ++id) {
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(id, info);
            cameras.put(info.facing);
        }
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(), "host-camera-capabilities.json").toPath(),
                cameras.toString().getBytes(StandardCharsets.UTF_8));
        server.start();
    }

    static String text(DataInputStream input) throws IOException {
        int size = input.readInt();
        if (size < 0 || size > 65536) throw new IOException("Camera parameter size");
        byte[] bytes = new byte[size];
        input.readFully(bytes);
        return new String(bytes, StandardCharsets.UTF_8);
    }

    static void text(DataOutputStream output, String value) throws IOException {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        output.writeInt(bytes.length);
        output.write(bytes);
    }

    private void serve(LocalSocket socket) throws Exception {
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x41313043 || input.readInt() != 1) throw new IOException("Camera protocol");
        int operation = input.readInt();
        if (operation == 1) {
            int count = Camera.getNumberOfCameras();
            output.writeInt(count);
            for (int id = 0; id < count; ++id) {
                Camera.CameraInfo info = new Camera.CameraInfo();
                Camera.getCameraInfo(id, info);
                output.writeInt(info.facing);
                output.writeInt(info.orientation);
            }
            output.flush();
        } else if (operation == 2) {
            int cameraId = input.readInt();
            if (context.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                output.writeInt(-13); output.flush(); return;
            }
            HostCameraSession session;
            try { session = new HostCameraSession(cameraId); }
            catch (Exception error) {
                android.util.Log.w("A10VM", "Host camera open", error);
                output.writeInt(-19); output.flush(); return;
            }
            int id = nextId.incrementAndGet();
            sessions.put(id, session);
            try {
                output.writeInt(0); output.writeInt(id); text(output, session.parameters()); output.flush();
                while (true) {
                    int command;
                    try { command = input.readInt(); }
                    catch (EOFException end) { return; }
                    if (command == 9) return;
                    String parameters = command == 2 ? text(input) : null;
                    int value = command == 8 || command == 10 ? input.readInt() : 0;
                    try {
                        String result = session.command(command, parameters, value);
                        output.writeInt(0);
                        if (command == 1 || command == 2) text(output, result);
                    } catch (Exception error) {
                        android.util.Log.w("A10VM", "Host camera command " + command, error);
                        output.writeInt(-22);
                    }
                    output.flush();
                }
            } finally {
                sessions.remove(id);
                session.close();
            }
        } else if (operation == 3) {
            HostCameraSession session = sessions.get(input.readInt());
            if (session == null) { output.writeInt(-19); output.flush(); return; }
            output.writeInt(0); output.flush();
            session.stream(output);
        } else {
            throw new IOException("Camera operation");
        }
    }

    @Override public void close() {
        server.close();
        for (HostCameraSession session : sessions.values()) session.close();
        sessions.clear();
    }
}
