package io.a10vm.guestruntime;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener2;
import android.hardware.SensorManager;
import android.net.LocalSocket;
import android.os.Handler;
import android.os.HandlerThread;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Host sensor subscriptions shared by the guest Sensors HAL command and polling channels. */
public final class HostSensorBridge implements AutoCloseable, SensorEventListener2 {
    private final SensorManager manager;
    private final HostStreamServer server;
    private final java.io.File capabilityFile;
    private final List<Sensor> sensors = new ArrayList<>();
    private final Map<Sensor, Integer> handles = new HashMap<>();
    private final Map<Integer, Long> periods = new HashMap<>();
    private final Map<Integer, Long> latencies = new HashMap<>();
    private final Map<Integer, Boolean> enabled = new HashMap<>();
    private final Map<Integer, Integer> flushes = new HashMap<>();
    private final ArrayDeque<Sample> events = new ArrayDeque<>();
    private HandlerThread thread;
    private Handler handler;
    private boolean running;
    private boolean invalidOrientationLogged;

    private static final class Sample {
        final long timestamp;
        final int handle, type, accuracy;
        final float[] values;
        Sample(long timestamp, int handle, int type, int accuracy, float[] values) {
            this.timestamp = timestamp; this.handle = handle; this.type = type;
            this.accuracy = accuracy; this.values = values;
        }
    }

    public HostSensorBridge(Context context) throws IOException {
        manager = context.getSystemService(SensorManager.class);
        capabilityFile = new java.io.File(context.getFilesDir(), "host-device-capabilities.json");
        for (Sensor sensor : manager.getSensorList(Sensor.TYPE_ALL)) {
            int mode = sensor.getReportingMode();
            if (sensor.isWakeUpSensor() || mode == Sensor.REPORTING_MODE_ONE_SHOT ||
                    sensor.getType() == Sensor.TYPE_STEP_COUNTER || sensor.getType() == Sensor.TYPE_STEP_DETECTOR ||
                    sensor.getType() == Sensor.TYPE_HEART_RATE || sensor.getType() == 32 /* dynamic meta */)
                continue;
            sensors.add(sensor);
            handles.put(sensor, sensors.size());
        }
        server = new HostStreamServer(context, "sensors", this::serve);
    }

    public synchronized void start() throws IOException {
        thread = new HandlerThread("host-sensors");
        thread.start();
        handler = new Handler(thread.getLooper());
        running = true;
        try {
            org.json.JSONArray types = new org.json.JSONArray(types());
            java.nio.file.Files.write(capabilityFile.toPath(),
                    ("{\"sensorTypes\":" + types + "}\n").getBytes(StandardCharsets.UTF_8));
            server.start();
        } catch (IOException error) { close(); throw error; }
    }

    public List<Integer> types() {
        List<Integer> result = new ArrayList<>();
        for (Sensor sensor : sensors) if (!result.contains(sensor.getType())) result.add(sensor.getType());
        return result;
    }

    private static void text(DataOutputStream output, String value) throws IOException {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        output.writeInt(bytes.length); output.write(bytes);
    }

    private void serve(LocalSocket socket) throws Exception {
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x41313053 || input.readInt() != 1) throw new IOException("Sensor protocol");
        switch (input.readInt()) {
            case 1:
                output.writeInt(sensors.size());
                for (int index = 0; index < sensors.size(); index++) {
                    Sensor sensor = sensors.get(index);
                    output.writeInt(index + 1); output.writeInt(sensor.getType());
                    text(output, sensor.getName()); text(output, sensor.getVendor());
                    text(output, sensor.getStringType());
                    output.writeInt(sensor.getVersion()); output.writeFloat(sensor.getMaximumRange());
                    output.writeFloat(sensor.getResolution()); output.writeFloat(sensor.getPower());
                    output.writeInt(sensor.getMinDelay() > 0 ? Math.max(5000, sensor.getMinDelay()) : 0);
                    output.writeInt(sensor.getMaxDelay());
                    output.writeInt(sensor.getReportingMode() << 1);
                }
                break;
            case 2: output.writeInt(activate(input.readInt(), input.readInt() != 0)); break;
            case 3: output.writeInt(batch(input.readInt(), input.readLong(), input.readLong())); break;
            case 4:
                int count = input.readInt();
                if (count < 1 || count > 256) throw new IOException("Sensor poll count");
                List<Sample> samples = poll(count);
                output.writeInt(samples.size());
                for (Sample sample : samples) {
                    output.writeLong(sample.timestamp); output.writeInt(sample.handle);
                    output.writeInt(sample.type); output.writeInt(sample.accuracy);
                    output.writeInt(sample.values.length);
                    for (float value : sample.values) output.writeFloat(value);
                }
                break;
            case 5: output.writeInt(flush(input.readInt())); break;
            default: throw new IOException("Sensor command");
        }
        output.flush();
    }

    private synchronized int activate(int handle, boolean active) {
        if (!running || handle < 1 || handle > sensors.size()) return -22;
        Sensor sensor = sensors.get(handle - 1);
        if (!active) {
            manager.unregisterListener(this, sensor); enabled.remove(handle);
            flushes.remove(handle);
            events.removeIf(sample -> sample.handle == handle);
            return 0;
        }
        try {
            long period = periods.containsKey(handle) ? periods.get(handle) : 20_000_000L;
            long latency = latencies.containsKey(handle) ? latencies.get(handle) : 0;
            if (!manager.registerListener(this, sensor, (int) Math.min(Integer.MAX_VALUE, period / 1000),
                    (int) Math.min(Integer.MAX_VALUE, latency / 1000), handler)) return -19;
            enabled.put(handle, true);
            return 0;
        } catch (SecurityException error) { return -13; }
    }

    private synchronized int batch(int handle, long period, long latency) {
        if (handle < 1 || handle > sensors.size() || period < 0 || latency < 0) return -22;
        periods.put(handle, Math.max(5_000_000L, period)); latencies.put(handle, latency);
        return enabled.containsKey(handle) ? activate(handle, true) : 0;
    }

    private synchronized int flush(int handle) {
        if (!enabled.containsKey(handle)) return -22;
        int pending = flushes.containsKey(handle) ? flushes.get(handle) : 0;
        flushes.put(handle, pending + 1);
        if (manager.flush(this)) return 0;
        if (pending == 0) flushes.remove(handle); else flushes.put(handle, pending);
        return -22;
    }

    private synchronized List<Sample> poll(int count) throws InterruptedException {
        while (events.isEmpty() && running) wait();
        List<Sample> result = new ArrayList<>();
        while (!events.isEmpty() && result.size() < count) result.add(events.removeFirst());
        return result;
    }

    private void enqueue(Sample sample) {
        if (events.size() >= 256) events.removeFirst();
        events.addLast(sample); notifyAll();
    }

    @Override public synchronized void onSensorChanged(SensorEvent event) {
        Integer handle = handles.get(event.sensor);
        if (!running || handle == null || !enabled.containsKey(handle)) return;
        float[] values = SensorEventValues.copy(event.sensor.getType(), event.values);
        if (values == null) {
            if (!invalidOrientationLogged) {
                android.util.Log.w("A10VM", "Ignoring host DEVICE_ORIENTATION outside Android 10 rotations: " +
                        java.util.Arrays.toString(event.values));
                invalidOrientationLogged = true;
            }
            return;
        }
        enqueue(new Sample(event.timestamp, handle, event.sensor.getType(), event.accuracy,
                values));
    }

    @Override public synchronized void onFlushCompleted(Sensor sensor) {
        Integer handle = handles.get(sensor);
        if (running && handle != null && enabled.containsKey(handle) && flushes.containsKey(handle)) {
            int pending = flushes.get(handle);
            if (pending == 1) flushes.remove(handle); else flushes.put(handle, pending - 1);
            enqueue(new Sample(android.os.SystemClock.elapsedRealtimeNanos(), handle, 0, 0, new float[0]));
        }
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    @Override public synchronized void close() {
        running = false; notifyAll();
        manager.unregisterListener(this);
        enabled.clear(); periods.clear(); latencies.clear(); flushes.clear(); events.clear();
        server.close();
        if (thread != null) { thread.quitSafely(); thread = null; }
        handler = null;
    }
}
