package io.a10vm.ui

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Build
import android.os.Bundle
import android.widget.*
import io.a10vm.runtime.VmConnection
import io.a10vm.runtime.VmService

class MainActivity : Activity() {
    private lateinit var dashboard: ManagementDashboard
    private lateinit var boot: BootAnimationView
    private var logDialog: AlertDialog? = null
    private var appPicker: InstalledAppsDialog? = null
    private var openOnStart = false
    private val vm by lazy { VmConnection(this, ::render, ::showLogs) }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        openOnStart = savedInstanceState?.getBoolean("openOnStart") == true
        dashboard = ManagementDashboard(this)
        boot = BootAnimationView(this, ::requestLogs)
        setContentView(FrameLayout(this).apply {
            addView(dashboard, FrameLayout.LayoutParams(-1, -1))
            addView(boot, FrameLayout.LayoutParams(-1, -1))
        })
        SystemUi.darkBars(window)
        dashboard.inspect.setOnClickListener { vm.perform(VmService.INSPECT) }
        dashboard.desktop.setOnClickListener { vm.perform(VmService.CHECK_DESKTOP) }
        dashboard.start.setOnClickListener {
            openOnStart = true
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED)
                vm.perform(VmService.START)
            else requestPermissions(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION,
                Manifest.permission.ACCESS_FINE_LOCATION), 5)
        }
        dashboard.fullscreen.setOnClickListener { openDisplay() }
        dashboard.install.setOnClickListener {
            AlertDialog.Builder(this).setTitle("导入应用")
                .setItems(arrayOf("从手机已安装应用选择", "选择 APK 文件")) { _, choice ->
                    if (choice == 0) {
                        appPicker?.dismiss()
                        appPicker = InstalledAppsDialog(this) { packages ->
                            vm.perform(VmService.IMPORT_APPS, org.json.JSONArray(packages).toString())
                        }.apply { show() }
                    } else selectApk()
                }.setNegativeButton("取消", null).show()
        }
        dashboard.importFiles.setOnClickListener {
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "*/*"
                addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }, 11)
        }
        dashboard.microphone.setOnClickListener {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED)
                vm.perform(VmService.ENABLE_MICROPHONE)
            else requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 3)
        }
        dashboard.camera.setOnClickListener {
            if (checkSelfPermission(Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED)
                vm.perform(VmService.ENABLE_CAMERA)
            else requestPermissions(arrayOf(Manifest.permission.CAMERA), 6)
        }
        dashboard.wifi.setOnClickListener {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED)
                openWifiPanel()
            else requestPermissions(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION,
                Manifest.permission.ACCESS_FINE_LOCATION), 4)
        }
        dashboard.stop.setOnClickListener { vm.perform(VmService.STOP) }
        dashboard.logs.setOnClickListener { requestLogs() }
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
    }
    override fun onStart() { super.onStart(); vm.bind() }
    override fun onStop() { logDialog?.dismiss(); vm.unbind(); super.onStop() }
    override fun onDestroy() { appPicker?.dismiss(); super.onDestroy() }
    @Deprecated("Activity permission API")
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 3 && grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED)
            vm.perform(VmService.ENABLE_MICROPHONE)
        if (requestCode == 4) { vm.refreshNetwork(); openWifiPanel() }
        if (requestCode == 5) vm.perform(VmService.START)
        if (requestCode == 6 && grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED)
            vm.perform(VmService.ENABLE_CAMERA)
    }
    @Deprecated("Activity result API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 10 && resultCode == RESULT_OK) {
            data?.data?.let { vm.perform(VmService.INSTALL_APK, it.toString()) }
        }
        if (requestCode == 11 && resultCode == RESULT_OK && data != null) {
            val uris = org.json.JSONArray()
            val selection = data.clipData
            if (selection != null) for (index in 0 until selection.itemCount) uris.put(selection.getItemAt(index).uri.toString())
            else data.data?.let { uris.put(it.toString()) }
            if (uris.length() > 0) vm.perform(VmService.IMPORT_FILES, uris.toString())
        }
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("openOnStart", openOnStart)
        super.onSaveInstanceState(outState)
    }
    private fun render(data: Bundle) {
        val state = data.getString("state", "IDLE")
        val running = state == "RUNNING"
        val busy = data.getBoolean("busy")
        val detail = data.getString("detail").orEmpty()
        dashboard.render(state, detail, busy)
        boot.setBooting(busy && (openOnStart || detail.startsWith("正在启动 Android 10")))
        boot.showLog(data.getString("bootSession").orEmpty(), data.getLong("bootSequence"),
            data.getLong("bootElapsedMillis"), data.getStringArrayList("bootLines").orEmpty())
        if (openOnStart && running && logDialog?.isShowing != true) { openOnStart = false; openDisplay() }
        if (state == "ERROR") openOnStart = false
    }
    private fun openDisplay() { startActivity(Intent(this, FullscreenActivity::class.java)) }
    private fun selectApk() {
        @Suppress("DEPRECATION")
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "application/vnd.android.package-archive"
            addCategory(Intent.CATEGORY_OPENABLE)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }, 10)
    }
    private fun openWifiPanel() { startActivity(io.a10vm.guestruntime.HostNetworkBridge.wifiSettingsIntent()) }
    private fun requestLogs() {
        logDialog?.dismiss()
        logDialog = AlertDialog.Builder(this).setTitle("运行记录").setMessage("正在读取运行记录…")
            .setNegativeButton("关闭", null).show()
        if (!vm.requestLogs()) {
            logDialog?.dismiss()
            Toast.makeText(this, "正在连接 Android 10，请稍后再试", Toast.LENGTH_SHORT).show()
        }
    }
    private fun showLogs(text: String) {
        logDialog?.dismiss()
        val content = TextView(this).apply {
            this.text = text; textSize = 12f; typeface = android.graphics.Typeface.MONOSPACE
            setTextIsSelectable(true); setPadding(dp(16), dp(12), dp(16), dp(12))
        }
        logDialog = AlertDialog.Builder(this).setTitle("运行记录").setView(ScrollView(this).apply { addView(content) })
            .setPositiveButton("复制记录") { _, _ ->
                getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("A10VM 运行记录", text))
                Toast.makeText(this, "运行记录已复制", Toast.LENGTH_SHORT).show()
            }.setNegativeButton("关闭", null).show()
    }
    private fun dp(value: Int) = (resources.displayMetrics.density * value).toInt()
}
