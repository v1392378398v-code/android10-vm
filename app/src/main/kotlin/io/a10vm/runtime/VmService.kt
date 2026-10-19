package io.a10vm.runtime

import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.*
import android.util.Log
import io.a10vm.nativedisplay.NativeWindow
import io.a10vm.ui.MainActivity
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class VmService : Service() {
    companion object {
        const val REGISTER = 1
        const val UNREGISTER = 2
        const val STATE = 3
        const val LOGS = 4
        const val REFRESH_NETWORK = 5
        const val INSPECT = "io.a10vm.INSPECT"
        const val START = "io.a10vm.START_NATIVE_DISPLAY"
        const val CHECK_DESKTOP = "io.a10vm.CHECK_DESKTOP_BOOT"
        const val STOP = "io.a10vm.STOP"
        const val INSTALL_APK = "io.a10vm.INSTALL_GUEST_APK"
        const val IMPORT_APPS = "io.a10vm.IMPORT_HOST_APPS"
        const val IMPORT_FILES = "io.a10vm.IMPORT_GUEST_FILES"
        const val ENABLE_MICROPHONE = "io.a10vm.ENABLE_MICROPHONE"
        const val ENABLE_CAMERA = "io.a10vm.ENABLE_CAMERA"
        const val CHANNEL = "native-display"
        @Volatile var window: NativeWindow? = null
            private set
    }
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { task ->
        Thread(task, "a10-runtime")
    }
    private val watcher = Executors.newSingleThreadScheduledExecutor()
    private val diagnosticWorker = Executors.newSingleThreadExecutor { task -> Thread(task, "a10-diagnostics") }
    private val busy = AtomicBoolean()
    private val clients = mutableListOf<Messenger>()
    private lateinit var session: NativeGraphicsSession
    @Volatile private var state = "IDLE"
    @Volatile private var destroyed = false
    private var microphoneForeground = false
    private var cameraForeground = false
    @Volatile private var detail = "点击启动进入 Android 10 桌面。"
    private val messenger = Messenger(Handler(Looper.getMainLooper()) { message ->
        when (message.what) {
            REGISTER -> { message.replyTo?.let { if (it !in clients) clients.add(it) }; session.refreshNetwork(); publish() }
            UNREGISTER -> clients.remove(message.replyTo)
            LOGS -> {
                val client = message.replyTo
                diagnosticWorker.execute {
                    val text = try { diagnosticText() }
                    catch (failure: Exception) { "读取运行记录失败，请稍后重试。\n${failure.message}" }
                    send(client, LOGS, Bundle().apply { putString("text", text) })
                }
            }
            REFRESH_NETWORK -> session.refreshNetwork()
        }
        true
    })
    override fun onCreate() {
        super.onCreate()
        session = NativeGraphicsSession(this)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Android 10", NotificationManager.IMPORTANCE_LOW),
        )
        watcher.scheduleWithFixedDelay({
            if (state == "BUSY") publish()
            if (state == "RUNNING") {
                val error = session.error()
                if (error.isNotEmpty() && busy.compareAndSet(false, true)) worker.execute {
                    try { window = null; session.close(); update("ERROR", error) }
                    catch (failure: Exception) { update("ERROR", "$error\n清理失败：${failure.message}") }
                    finally { busy.set(false); publish(); microphoneForeground = false; stopForeground(STOP_FOREGROUND_REMOVE) }
                } else {
                    if (!busy.get()) worker.execute {
                        try { session.updateDisplayPower() }
                        catch (failure: Exception) { Log.w("A10VM_NATIVE", "Display power: ${failure.message}") }
                    }
                    publish()
                }
            }
        }, 250, 250, TimeUnit.MILLISECONDS)
    }
    override fun onBind(intent: Intent) = messenger.binder
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (destroyed || intent?.action !in setOf(INSPECT, START, STOP, CHECK_DESKTOP, INSTALL_APK, IMPORT_APPS, IMPORT_FILES, ENABLE_MICROPHONE, ENABLE_CAMERA)) return START_NOT_STICKY
        microphoneForeground = checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED &&
            (microphoneForeground || intent?.action == START || intent?.action == ENABLE_MICROPHONE)
        cameraForeground = checkSelfPermission(android.Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED &&
            (cameraForeground || intent?.action == START || intent?.action == ENABLE_CAMERA)
        val foregroundTypes = (if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0) or
            (if (Build.VERSION.SDK_INT >= 30 && microphoneForeground) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0) or
            (if (Build.VERSION.SDK_INT >= 30 && cameraForeground) ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA else 0)
        if (Build.VERSION.SDK_INT >= 29) startForeground(10, notification(), foregroundTypes)
        else startForeground(10, notification())
        if (!busy.compareAndSet(false, true)) return START_NOT_STICKY
        update("BUSY", when (intent?.action) {
            START -> "正在启动 Android 10 框架、私有 Binder 与原生显示。"
            CHECK_DESKTOP -> "正在检查 Android 10 桌面启动。"
            INSTALL_APK -> "正在将 APK 安装到 Android 10…"
            IMPORT_APPS -> "正在导入已选择的手机应用…"
            IMPORT_FILES -> "正在导入客体文件并更新图库…"
            else -> "正在处理原生显示操作。"
        })
        worker.execute {
            val background = intent?.action in setOf(INSTALL_APK, IMPORT_APPS, IMPORT_FILES)
            Process.setThreadPriority(if (background) Process.THREAD_PRIORITY_BACKGROUND else Process.THREAD_PRIORITY_DEFAULT)
            try {
                when (intent?.action) {
                    INSPECT -> update(if (session.alive) "RUNNING" else "IDLE", session.inspect())
                    CHECK_DESKTOP -> update("IDLE", session.checkDesktop())
                    START -> {
                        if (!session.alive) session.start()
                        window = session.window
                        update("RUNNING", "Android 10 系统服务已启动 · 宿主 GPU 合成 · 客体 InputManager 触摸")
                    }
                    STOP -> { window = null; session.close(); update("IDLE", "Android 10 已停止。") }
                    ENABLE_MICROPHONE -> update(if (session.alive) "RUNNING" else "IDLE",
                        if (microphoneForeground) "麦克风已开启。请在 Android 10 内允许应用录音。" else "请先允许 A10VM 使用麦克风。")
                    ENABLE_CAMERA -> update(if (session.alive) "RUNNING" else "IDLE",
                        if (cameraForeground) "相机已开启。请在 Android 10 内允许应用使用相机。" else "请先允许 A10VM 使用相机。")
                    INSTALL_APK -> {
                        require(session.alive) { "请先启动 Android 10" }
                        val uri = android.net.Uri.parse(requireNotNull(intent.getStringExtra("uri")))
                        try { update("RUNNING", GuestApkImport(this).install(uri, session)) }
                        catch (failure: Exception) { update("RUNNING", "APK 安装失败：${failure.message}") }
                    }
                    IMPORT_APPS -> {
                        require(session.alive) { "请先启动 Android 10" }
                        try {
                            val packages = org.json.JSONArray(requireNotNull(intent.getStringExtra("uri")))
                            val result = GuestApkImport(this).importInstalled(packages, session) { progress ->
                                update("BUSY", progress)
                            }
                            update("RUNNING", result)
                        } catch (failure: Exception) { update("RUNNING", "应用导入失败：${failure.message}") }
                    }
                    IMPORT_FILES -> {
                        require(session.alive) { "请先启动 Android 10" }
                        try {
                            val uris = org.json.JSONArray(requireNotNull(intent.getStringExtra("uri")))
                            update("RUNNING", GuestFileImport(this).importFiles(uris, session))
                        } catch (failure: Exception) { update("RUNNING", "文件导入失败：${failure.message}") }
                    }
                }
            } catch (failure: Exception) { failed(failure, "操作失败") }
            catch (failure: LinkageError) { failed(failure, "原生组件装载失败") }
            finally {
                Process.setThreadPriority(Process.THREAD_PRIORITY_DEFAULT)
                busy.set(false)
                if (!session.alive) {
                    microphoneForeground = false
                    cameraForeground = false
                    stopForeground(STOP_FOREGROUND_REMOVE)
                }
                publish()
            }
        }
        return START_NOT_STICKY
    }
    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("A10VM · Android 10").setContentText("桌面运行中")
            .setContentIntent(open).setOngoing(true).build()
    }
    private fun update(value: String, message: String) {
        Log.i("A10VM_NATIVE", "$value: $message")
        state = value; detail = message; publish()
        val entry = "${java.util.Date()}\nstate=$value\n${message.take(1500)}\n"
        diagnosticWorker.execute {
            try {
                java.io.File(filesDir, "guest-runtime/session-state.log").apply {
                    parentFile?.mkdirs()
                    writeText(entry, Charsets.UTF_8)
                }
            } catch (failure: Exception) { Log.w("A10VM_NATIVE", "State log: ${failure.message}") }
        }
    }
    @Suppress("DEPRECATION")
    private fun diagnosticText(): String {
        val info = packageManager.getPackageInfo(packageName, 0)
        return "A10VM 运行记录（详细信息）\n时间：${java.util.Date()}\n" +
            "应用：$packageName ${info.versionName} (${info.longVersionCode})\n" +
            "设备：${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE}\n" +
            "内核：${System.getProperty("os.version")}\n状态：$state\n最近操作：${detail.take(2400)}\n" + session.logs()
    }
    private fun failed(failure: Throwable, stage: String) {
        window = null
        try { session.close() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
        val cleanup = failure.suppressed.joinToString("\n") { "清理失败：${it.message}" }
        update("ERROR", "$stage：${failure.message}" + if (cleanup.isEmpty()) "" else "\n$cleanup")
    }
    private fun publish() = main.post {
        if (destroyed || clients.isEmpty()) return@post
        val renderer = window
        val metrics = renderer?.metrics() ?: LongArray(17)
        val data = Bundle().apply {
            putString("state", state); putString("detail", detail); putBoolean("busy", busy.get())
            if (state == "BUSY") {
                val boot = session.bootLog()
                if (boot.active) {
                    putString("bootSession", boot.session); putLong("bootSequence", boot.sequence)
                    putLong("bootElapsedMillis", boot.elapsedMillis); putStringArrayList("bootLines", boot.lines)
                }
            }
            putBoolean("frameReady", metrics[2] > 0 && metrics[16] == metrics[6])
            putLong("frames", metrics[1]); putLong("inputSequence", metrics[3]); putLong("echoSequence", metrics[4])
            putString("gpu", renderer?.description()); putLong("uptimeSeconds", session.uptimeSeconds)
        }
        clients.toList().forEach { if (!send(it, STATE, data)) clients.remove(it) }
    }
    private fun send(client: Messenger?, what: Int, data: Bundle): Boolean = try {
        client?.send(Message.obtain(null, what).apply { this.data = data }); true
    } catch (_: RemoteException) { false }
    override fun onDestroy() {
        destroyed = true
        watcher.shutdownNow()
        window = null
        clients.clear()
        main.removeCallbacksAndMessages(null)
        worker.execute {
            try { session.close() }
            catch (failure: Exception) { Log.e("A10VM_NATIVE", "Session cleanup failed", failure) }
            finally { diagnosticWorker.shutdown() }
        }
        worker.shutdown()
        super.onDestroy()
    }
}
