package io.a10vm.runtime

import android.content.Context
import android.os.SystemClock
import io.a10vm.nativedisplay.GuestLibraryFiles
import io.a10vm.nativedisplay.NativeWindow
import io.a10vm.guestruntime.GuestRuntime
import io.a10vm.guestruntime.FrameworkSession
import io.a10vm.guestruntime.HostNetworkBridge
import io.a10vm.guestruntime.HostAudioBridge
import io.a10vm.guestruntime.HostSensorBridge
import io.a10vm.guestruntime.HostVibratorBridge
import io.a10vm.guestruntime.HostBatteryBridge
import io.a10vm.guestruntime.HostCameraBridge
import io.a10vm.guestruntime.HostSharedMemoryBridge
import java.io.File
import java.util.UUID

class NativeGraphicsSession(context: Context) : AutoCloseable {
    private companion object {
        // The guest boots SurfaceFlinger and system_server before it composes for the first time;
        // the host GPU endpoint is live as soon as it answers, not when the guest is ready.
        const val GPU_READY_MILLIS = 30_000L
        const val FIRST_FRAME_MILLIS = 120_000L
    }

    private val directory = File(context.filesDir.canonicalFile, "native-window")
    private val files = GuestLibraryFiles(context, directory)
    private val runtime = GuestRuntime(context, File(context.filesDir, "guest-runtime"))
    private val nonce = UUID.randomUUID().toString()
    private val network = HostNetworkBridge(context)
    private val audio = HostAudioBridge(context)
    private val sensors = HostSensorBridge(context)
    private val vibrator = HostVibratorBridge(context)
    private val battery = HostBatteryBridge(context)
    private val camera = HostCameraBridge(context)
    private val sharedMemory = HostSharedMemoryBridge(context)
    @Volatile var window: NativeWindow? = null
        private set
    @Volatile private var framework: FrameworkSession? = null
    private var startedAt = 0L
    private var displayInteractive: Boolean? = null
    val alive get() = window != null && framework?.isAlive == true
    val uptimeSeconds get() = if (alive) (SystemClock.elapsedRealtime() - startedAt) / 1000 else 0L

    fun inspect(): String {
        val manifest = files.readInputs("native-display-inputs.json")
        check(manifest.getString("backend") == "native-arm64-gles-surface")
        check(!manifest.getBoolean("rootRequired") && manifest.getBoolean("desktopImplemented"))
        files.verifyInputs(manifest.getJSONArray("files"))
        runtime.verify()
        return "Android 10 桌面、ART、私有 Binder 及图形组件校验通过。"
    }

    fun start() {
        check(!alive) { "原生显示已经运行" }
        val log = runtime.startupLog()
        log.begin()
        try {
            log.record("VERIFY", "Checking display and Android runtime")
            inspect()
            directory.mkdirs()
            log.record("PREPARE", "Preparing private Android filesystem")
            runtime.prepare()
            for (name in listOf("gpu.sock", "desktop-input.sock")) File(directory, name).delete()
            startedAt = SystemClock.elapsedRealtime()
            sharedMemory.start()
            log.record("SHMEM", "Shared memory bridge ready")
            log.record("ART", "Checking Android Java runtime")
            runtime.checkJava(nonce)
            log.record("ART", "Runtime identity verified")
            startHostDevices()
            log.record("DEVICES", "Host device bridges ready")
            val renderer = NativeWindow(directory).also { window = it }
            await("宿主 GPU 初始化", GPU_READY_MILLIS) { renderer.metrics()[0] != 0L }
            log.record("GPU", "Host renderer ready; starting Android services")
            framework = runtime.startDesktop(nonce, File(directory, "gpu.sock"), File(directory, "desktop-input.sock"))
            await("Android 10 合成首帧", FIRST_FRAME_MILLIS) { renderer.metrics()[1] > 0L }
            log.record("READY", "Android desktop, input and first frame ready")
        } catch (failure: Throwable) {
            log.record("ERROR", failure.message ?: failure.javaClass.simpleName)
            try { close() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
            throw failure
        } finally { log.finish() }
    }

    fun checkDesktop(): String {
        check(!alive) { "请先停止当前运行，再检查桌面启动" }
        inspect()
        runtime.prepare()
        try {
            sharedMemory.start()
            startHostDevices()
            runtime.startDesktop(nonce).use {
                return "Android 10 系统服务及 Launcher3 桌面启动检查通过。"
            }
        } finally { close() }
    }

    private fun startHostDevices() {
        network.start()
        audio.start()
        sensors.start()
        vibrator.start()
        battery.start()
        camera.start()
        runtime.configureHostDevices(if (vibrator.available()) emptySet() else setOf(HostVibratorBridge.HAL_NAME))
    }

    fun installApk(apk: File): String = checkNotNull(framework) { "请先启动 Android 10" }.installApk(apk)
    fun installApks(apks: List<File>): String = checkNotNull(framework) { "请先启动 Android 10" }.installApks(apks)

    fun refreshNetwork() = network.refresh()

    fun updateDisplayPower() {
        val renderer = window ?: return
        val services = framework ?: return
        val interactive = renderer.metrics()[9] != 0L
        if (interactive == displayInteractive) return
        displayInteractive = interactive
        services.setDisplayInteractive(interactive)
    }

    private fun await(stage: String, timeoutMillis: Long, ready: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMillis
        while (!ready()) {
            check(window?.error().isNullOrEmpty()) { window?.error().orEmpty() }
            check(framework?.isAlive != false) { "Android 10 系统进程退出：${logs()}" }
            check(SystemClock.elapsedRealtime() < deadline) { "$stage 超时：${logs()}" }
            Thread.sleep(10)
        }
    }

    fun logs(): String = runtime.diagnostics()
    fun bootLog() = runtime.startupLog().snapshot()
    fun scanMedia(path: String) = requireNotNull(framework) { "请先启动 Android 10" }.scanMedia(path)
    fun error(): String = window?.error().orEmpty().ifEmpty {
        framework?.error().orEmpty()
    }
    override fun close() {
        val renderer = window
        val services = framework
        window = null
        framework = null
        displayInteractive = null
        try {
            renderer?.requestExit()
            services?.close()
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            throw interrupted
        } finally {
            audio.close()
            sensors.close()
            vibrator.close()
            battery.close()
            camera.close()
            sharedMemory.close()
            network.close()
            renderer?.close()
        }
    }
}
