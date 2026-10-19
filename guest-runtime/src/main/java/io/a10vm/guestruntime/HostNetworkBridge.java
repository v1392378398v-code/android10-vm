package io.a10vm.guestruntime;

import android.content.Context;
import android.content.BroadcastReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.DhcpInfo;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.ProxyInfo;
import android.net.RouteInfo;
import android.net.wifi.WifiInfo;
import android.net.wifi.ScanResult;
import android.net.wifi.WifiManager;
import android.net.wifi.SupplicantState;
import android.location.LocationManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.FileObserver;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import java.io.File;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Publishes the host default network and routes Wi-Fi radio controls to the system panel. */
public final class HostNetworkBridge implements AutoCloseable {
    private final Context context;
    private final ConnectivityManager manager;
    private final WifiManager wifi;
    private final File directory;
    private HandlerThread thread;
    private Handler handler;
    private FileObserver actions;
    private boolean receiverRegistered;
    private long actionSequence;
    private Boolean scanUpdated;
    private final Map<Network, WifiInfo> wifiConnections = new HashMap<>();
    private final WifiEvents wifiCallback;
    private boolean wifiRegistered;
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (WifiManager.SCAN_RESULTS_AVAILABLE_ACTION.equals(intent.getAction()))
                scanUpdated = intent.getBooleanExtra(WifiManager.EXTRA_RESULTS_UPDATED, false);
            if (LocationManager.MODE_CHANGED_ACTION.equals(intent.getAction())) { refresh(); return; }
            publish();
        }
    };
    private final ConnectivityManager.NetworkCallback callback = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(Network network) { publish(); }
        @Override public void onLost(Network network) { publish(); }
        @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) { publish(); }
        @Override public void onLinkPropertiesChanged(Network network, LinkProperties links) { publish(); }
        @Override public void onBlockedStatusChanged(Network network, boolean blocked) { publish(); }
    };
    private boolean registered;

    private final class WifiEvents extends ConnectivityManager.NetworkCallback {
        WifiEvents() { super(); }
        @android.annotation.TargetApi(31)
        WifiEvents(int flags) { super(flags); }
        @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) {
            synchronized (HostNetworkBridge.this) {
                if (Build.VERSION.SDK_INT >= 29 && caps.getTransportInfo() instanceof WifiInfo)
                    wifiConnections.put(network, (WifiInfo) caps.getTransportInfo());
                else wifiConnections.remove(network);
                publish();
            }
        }
        @Override public void onLost(Network network) {
            synchronized (HostNetworkBridge.this) { wifiConnections.remove(network); publish(); }
        }
    }

    public HostNetworkBridge(Context context) throws Exception {
        this.context = context.getApplicationContext();
        manager = context.getSystemService(ConnectivityManager.class);
        wifi = context.getApplicationContext().getSystemService(WifiManager.class);
        directory = context.getFilesDir().getCanonicalFile();
        wifiCallback = Build.VERSION.SDK_INT >= 31
                ? new WifiEvents(ConnectivityManager.NetworkCallback.FLAG_INCLUDE_LOCATION_INFO) : new WifiEvents();
    }

    public synchronized void start() throws Exception {
        if (registered) return;
        thread = new HandlerThread("host-network");
        thread.start();
        handler = new Handler(thread.getLooper());
        try {
            manager.registerDefaultNetworkCallback(callback, handler);
            registered = true;
            registerWifiCallback();
            IntentFilter filter = new IntentFilter();
            for (String action : new String[] {WifiManager.WIFI_STATE_CHANGED_ACTION,
                    WifiManager.NETWORK_STATE_CHANGED_ACTION, WifiManager.RSSI_CHANGED_ACTION,
                    WifiManager.SCAN_RESULTS_AVAILABLE_ACTION, LocationManager.MODE_CHANGED_ACTION}) filter.addAction(action);
            if (Build.VERSION.SDK_INT >= 33)
                context.registerReceiver(receiver, filter, null, handler, Context.RECEIVER_NOT_EXPORTED);
            else context.registerReceiver(receiver, filter, null, handler);
            receiverRegistered = true;
            Files.deleteIfExists(new File(directory, "host-wifi-action.json").toPath());
            actions = new FileObserver(directory.getPath(), FileObserver.MOVED_TO) {
                @Override public void onEvent(int event, String name) {
                    if ("host-wifi-action.json".equals(name)) handler.post(HostNetworkBridge.this::readAction);
                }
            };
            actions.startWatching();
            writeSnapshot();
        } catch (Exception error) { close(); throw error; }
    }

    private void registerWifiCallback() {
        if (wifi == null) return;
        manager.registerNetworkCallback(new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), wifiCallback, handler);
        wifiRegistered = true;
    }

    public synchronized void refresh() {
        if (handler == null) return;
        handler.post(() -> {
            synchronized (HostNetworkBridge.this) {
                if (!registered) return;
                try {
                    // Re-request capabilities after a permission change; cached callbacks can be redacted.
                    if (wifiRegistered) { manager.unregisterNetworkCallback(wifiCallback); wifiRegistered = false; }
                    wifiConnections.clear();
                    registerWifiCallback();
                    publish();
                } catch (Exception error) { Log.e("A10VM", "Refresh host Wi-Fi", error); }
            }
        });
    }

    private static int mtu(LinkProperties links) {
        if (Build.VERSION.SDK_INT >= 29) return links.getMtu();
        try {
            java.net.NetworkInterface network = java.net.NetworkInterface.getByName(links.getInterfaceName());
            if (network != null) return network.getMTU();
        } catch (java.net.SocketException ignored) { }
        return 1500;
    }

    private WifiInfo connectionInfo(Network network) {
        WifiInfo info = wifiConnections.get(network);
        if (info != null) return info;
        info = wifi.getConnectionInfo();
        for (WifiInfo candidate : wifiConnections.values()) {
            if (candidate.getSupplicantState() == SupplicantState.COMPLETED && (info == null ||
                    candidate.getNetworkId() == info.getNetworkId() || WifiManager.UNKNOWN_SSID.equals(info.getSSID())))
                return candidate;
        }
        return info;
    }

    private void readAction() {
        try {
            File request = new File(directory, "host-wifi-action.json");
            if (!request.isFile() || !registered) return;
            String action = new JSONObject(new String(Files.readAllBytes(request.toPath()),
                    StandardCharsets.UTF_8)).getString("action");
            Files.deleteIfExists(request.toPath());
            if ("panel".equals(action)) context.startActivity(wifiSettingsIntent()
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            else if ("scan".equals(action)) scanUpdated = wifi != null && wifi.startScan();
            else throw new IllegalArgumentException("Unknown Wi-Fi relay action");
            actionSequence++;
            writeSnapshot();
        } catch (Exception error) { Log.e("A10VM", "Host Wi-Fi action", error); }
    }

    public static Intent wifiSettingsIntent() {
        return new Intent(Build.VERSION.SDK_INT >= 29 ? Settings.Panel.ACTION_WIFI : Settings.ACTION_WIFI_SETTINGS);
    }

    private void publish() {
        try { writeSnapshot(); }
        catch (Exception error) { Log.e("A10VM", "Host network snapshot", error); }
    }

    private synchronized void writeSnapshot() throws Exception {
        if (!registered) return;
        Network network = manager.getActiveNetwork();
        NetworkCapabilities caps = network == null ? null : manager.getNetworkCapabilities(network);
        LinkProperties links = network == null ? null : manager.getLinkProperties(network);
        boolean connected = caps != null && links != null;
        JSONObject snapshot = new JSONObject().put("connected", connected)
                .put("hostNetId", connected ? network.getNetworkHandle() >>> 32 : 0);
        if (wifi != null) {
            JSONObject wireless = new JSONObject().put("state", wifi.getWifiState())
                    .put("dualBand", wifi.is5GHzBandSupported());
            WifiInfo info = connectionInfo(network);
            wireless.put("connected", wireless.getInt("state") == WifiManager.WIFI_STATE_ENABLED
                    && info != null && info.getSupplicantState() == SupplicantState.COMPLETED);
            wireless.put("locationPermission", context.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION)
                    == PackageManager.PERMISSION_GRANTED);
            LocationManager location = context.getSystemService(LocationManager.class);
            wireless.put("locationEnabled", location != null && location.isLocationEnabled());
            if (info != null) wireless.put("ssid", info.getSSID()).put("bssid", info.getBSSID())
                    .put("mac", info.getMacAddress()).put("networkId", info.getNetworkId())
                    .put("rssi", info.getRssi()).put("frequency", info.getFrequency())
                    .put("linkSpeed", info.getLinkSpeed()).put("ip", info.getIpAddress());
            if (info != null && Build.VERSION.SDK_INT >= 31) wireless.put("security", info.getCurrentSecurityType());
            DhcpInfo dhcp = wifi.getDhcpInfo();
            if (dhcp != null) wireless.put("dhcp", new JSONObject().put("ipAddress", dhcp.ipAddress)
                    .put("gateway", dhcp.gateway).put("netmask", dhcp.netmask).put("dns1", dhcp.dns1)
                    .put("dns2", dhcp.dns2).put("serverAddress", dhcp.serverAddress).put("leaseDuration", dhcp.leaseDuration));
            JSONArray scans = new JSONArray();
            if (context.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                try {
                    for (ScanResult scan : wifi.getScanResults()) scans.put(new JSONObject().put("ssid", scan.SSID)
                            .put("bssid", scan.BSSID).put("frequency", scan.frequency).put("level", scan.level)
                            .put("capabilities", scan.capabilities).put("timestamp", scan.timestamp));
                } catch (SecurityException error) { Log.w("A10VM", "Wi-Fi scan access", error); }
            }
            wireless.put("scans", scans);
            snapshot.put("wifi", wireless);
        }
        if (actionSequence != 0) snapshot.put("wifiAction", actionSequence);
        if (scanUpdated != null) snapshot.put("scanUpdated", scanUpdated);
        if (connected) {
            JSONArray transports = new JSONArray();
            for (int type : new int[] {0, 1, 2, 3, 4, 5, 6})
                if (caps.hasTransport(type)) transports.put(type);
            snapshot.put("transports", transports)
                    .put("internet", caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET))
                    .put("validated", caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
                    .put("notMetered", caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED))
                    .put("notRoaming", caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_ROAMING))
                    .put("notSuspended", caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED))
                    .put("downstreamKbps", caps.getLinkDownstreamBandwidthKbps())
                    .put("upstreamKbps", caps.getLinkUpstreamBandwidthKbps())
                    .put("interface", links.getInterfaceName()).put("mtu", mtu(links))
                    .put("domains", links.getDomains());
            JSONArray addresses = new JSONArray(), dns = new JSONArray(), routes = new JSONArray();
            for (LinkAddress address : links.getLinkAddresses()) addresses.put(address.toString());
            for (InetAddress address : links.getDnsServers()) dns.put(address.getHostAddress());
            for (RouteInfo route : links.getRoutes()) {
                routes.put(new JSONObject().put("destination", route.getDestination().toString())
                        .put("gateway", route.getGateway() == null ? "" : route.getGateway().getHostAddress())
                        .put("interface", route.getInterface()).put("type", Build.VERSION.SDK_INT >= 33 ? route.getType() : 1));
            }
            snapshot.put("addresses", addresses).put("dns", dns).put("routes", routes);
            ProxyInfo proxy = links.getHttpProxy();
            if (proxy != null) snapshot.put("proxy", new JSONObject().put("host", proxy.getHost())
                    .put("port", proxy.getPort()).put("exclusions", new JSONArray(proxy.getExclusionList()))
                    .put("pac", proxy.getPacFileUrl().toString()));
            snapshot.put("privateDnsActive", links.isPrivateDnsActive())
                    .put("privateDnsName", links.getPrivateDnsServerName());
            if (Build.VERSION.SDK_INT >= 30 && links.getNat64Prefix() != null)
                snapshot.put("nat64", links.getNat64Prefix().toString());
        }
        // Publish the ID first: a new guest agent must bind sockets to the new host network.
        atomicWrite("host-network-id", snapshot.getLong("hostNetId") + "\n");
        atomicWrite("host-network.json", snapshot.toString() + "\n");
    }

    private void atomicWrite(String name, String text) throws Exception {
        File target = new File(directory, name), pending = new File(directory, name + ".tmp");
        Files.write(pending.toPath(), text.getBytes(StandardCharsets.UTF_8));
        Files.move(pending.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    @Override public synchronized void close() {
        if (actions != null) { actions.stopWatching(); actions = null; }
        if (receiverRegistered) { context.unregisterReceiver(receiver); receiverRegistered = false; }
        if (wifiRegistered) { manager.unregisterNetworkCallback(wifiCallback); wifiRegistered = false; }
        wifiConnections.clear();
        if (registered) { manager.unregisterNetworkCallback(callback); registered = false; }
        if (thread != null) { thread.quitSafely(); thread = null; }
        handler = null;
    }
}
