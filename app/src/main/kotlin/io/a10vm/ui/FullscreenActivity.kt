package io.a10vm.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import io.a10vm.nativedisplay.NativeSurfaceView
import io.a10vm.runtime.VmConnection
import io.a10vm.runtime.VmService

class FullscreenActivity : Activity() {
    private lateinit var display: NativeSurfaceView
    private lateinit var status: TextView
    private val vm by lazy { VmConnection(this, ::render, onDisconnected = {
        display.connect(null); status.text = "与 Android 10 的连接已断开，请返回管理页重试。"; status.visibility = View.VISIBLE
    }) }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.attributes = window.attributes.apply {
            preferredRefreshRate = io.a10vm.nativedisplay.WindowBridge.REFRESH_HZ.toFloat()
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        display = NativeSurfaceView(this).apply { contentDescription = "Android 10 桌面" }
        root.addView(display, FrameLayout.LayoutParams(-1, -1, Gravity.CENTER))
        status = TextView(this).apply {
            textSize = 16f; setTextColor(Color.WHITE); gravity = Gravity.CENTER; text = "正在显示桌面，请稍候…"
        }
        root.addView(status, FrameLayout.LayoutParams(-1, -2, Gravity.CENTER))
        val management = EdgeFloatingButton(this).apply {
            setOnClickListener {
                startActivity(Intent(this@FullscreenActivity, MainActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                })
                finish()
            }
        }
        root.addView(management, FrameLayout.LayoutParams(management.buttonSize, management.buttonSize))
        var safe = SystemUi.Insets(0, 0, 0, 0)
        fun positionManagement() {
            management.setSafeArea(safe.left, safe.top, root.width - safe.right, root.height - safe.bottom)
        }
        root.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> positionManagement() }
        root.setOnApplyWindowInsetsListener { _, insets ->
            safe = SystemUi.insets(insets, includeHiddenBars = true)
            positionManagement()
            insets
        }
        setContentView(root)
        hideSystemBars()
    }
    override fun onStart() { super.onStart(); vm.bind() }
    override fun onStop() { vm.unbind(); display.connect(null); super.onStop() }
    override fun onWindowFocusChanged(hasFocus: Boolean) { super.onWindowFocusChanged(hasFocus); if (hasFocus) hideSystemBars() }
    private fun render(data: Bundle) {
        val running = data.getString("state") == "RUNNING"
        display.connect(if (running) VmService.window else null)
        status.visibility = if (running && data.getBoolean("frameReady")) View.GONE else View.VISIBLE
        status.text = if (running) "正在显示桌面，请稍候…" else "桌面尚未打开，请返回管理页启动 Android 10。"
    }
    private fun hideSystemBars() {
        SystemUi.fullscreen(window)
    }
}
