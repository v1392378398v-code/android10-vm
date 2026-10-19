package io.a10vm.guestruntime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.LocalSocket;
import android.os.BatteryManager;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** Battery broadcasts and public properties, without reading host sysfs. */
public final class HostBatteryBridge implements AutoCloseable {
    private final Context context;
    private final BatteryManager manager;
    private final HostStreamServer server;
    private volatile Intent battery;
    private boolean registered;
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { battery = intent; }
    };

    public HostBatteryBridge(Context context) throws IOException {
        this.context = context.getApplicationContext();
        manager = context.getSystemService(BatteryManager.class);
        server = new HostStreamServer(context, "battery", this::serve);
    }

    public synchronized void start() throws IOException {
        battery = context.registerReceiver(receiver, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        registered = true;
        try { server.start(); }
        catch (IOException error) { close(); throw error; }
    }

    private void serve(LocalSocket socket) throws Exception {
        socket.setSoTimeout(3000);
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x41313042 || input.readInt() != 1 || input.readInt() != 1)
            throw new IOException("Battery protocol");
        Intent snapshot = battery;
        output.writeInt(snapshot == null ? -19 : 0);
        if (snapshot != null) {
            int level = snapshot.getIntExtra(BatteryManager.EXTRA_LEVEL, 0);
            int scale = snapshot.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
            output.writeInt(snapshot.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0));
            output.writeInt(snapshot.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN));
            output.writeInt(snapshot.getIntExtra(BatteryManager.EXTRA_HEALTH, BatteryManager.BATTERY_HEALTH_UNKNOWN));
            output.writeInt(snapshot.getBooleanExtra(BatteryManager.EXTRA_PRESENT, true) ? 1 : 0);
            output.writeInt(scale > 0 ? (int) Math.max(0, Math.min(100, (long) level * 100 / scale)) : 0);
            output.writeInt(snapshot.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0));
            output.writeInt(snapshot.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0));
            String technology = snapshot.getStringExtra(BatteryManager.EXTRA_TECHNOLOGY);
            byte[] bytes = (technology == null ? "" : technology).getBytes(StandardCharsets.UTF_8);
            output.writeInt(bytes.length); output.write(bytes);
            for (int property : new int[] {BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER,
                    BatteryManager.BATTERY_PROPERTY_CURRENT_NOW, BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE})
                output.writeInt(manager.getIntProperty(property));
            output.writeLong(manager.getLongProperty(BatteryManager.BATTERY_PROPERTY_ENERGY_COUNTER));
        }
        output.flush();
    }

    @Override public synchronized void close() {
        server.close();
        if (registered) { context.unregisterReceiver(receiver); registered = false; }
        battery = null;
    }
}
