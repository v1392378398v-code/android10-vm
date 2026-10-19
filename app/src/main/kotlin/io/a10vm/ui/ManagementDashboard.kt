package io.a10vm.ui

import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.animation.StateListAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.animation.DecelerateInterpolator
import android.widget.*
import io.a10vm.R

/** Presentation and motion for the management page; session actions stay in the activity. */
class ManagementDashboard(context: Context) : ScrollView(context) {
    private val ink = Color.rgb(235, 245, 241)
    private val muted = Color.rgb(155, 177, 170)
    private val mint = Color.rgb(114, 226, 185)
    private val column = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val status = label("正在连接", 12f, mint).apply {
        setPadding(dp(12), dp(6), dp(12), dp(6))
        background = shape(Color.rgb(30, 63, 51), 18)
    }
    private val detail = label("正在连接你的桌面…", 14f, muted).apply {
        setLineSpacing(dp(4).toFloat(), 1f)
        maxLines = 4
        ellipsize = android.text.TextUtils.TruncateAt.END
    }
    private val progress = ProgressBar(context, null, android.R.attr.progressBarStyleHorizontal).apply {
        isIndeterminate = true
        indeterminateTintList = ColorStateList.valueOf(mint)
        visibility = View.GONE
    }
    val start = action("启动 Android 10 桌面", primary = true)
    val fullscreen = action("进入 Android 10 桌面", primary = true).apply { visibility = View.GONE }
    val install = action("导入应用到 Android 10")
    val importFiles = action("导入图片、视频和文件")
    val microphone = action("开启麦克风")
    val camera = action("开启相机")
    val wifi = action("设置手机 Wi-Fi")
    val inspect = action("检查运行环境")
    val desktop = action("测试桌面能否启动")
    val stop = action("停止 Android 10").apply { setTextColor(Color.rgb(245, 169, 153)) }
    val logs = action("查看运行记录")
    private var renderedState = ""
    private var entered = false

    init {
        isFillViewport = true
        isVerticalScrollBarEnabled = false
        clipToPadding = false
        setBackgroundColor(Color.rgb(12, 21, 23))
        addView(column, LayoutParams(-1, -2))
        column.setPadding(dp(22), dp(24), dp(22), dp(24))
        column.setOnApplyWindowInsetsListener { view, insets ->
            val bars = SystemUi.insets(insets)
            view.setPadding(dp(22) + bars.left, dp(24) + bars.top, dp(22) + bars.right, dp(24) + bars.bottom)
            insets
        }
        val header = LinearLayout(context).apply {
            gravity = Gravity.CENTER_VERTICAL
            addView(ImageView(context).apply {
                setImageResource(R.drawable.ic_launcher)
                importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            },
                LinearLayout.LayoutParams(dp(38), dp(38)))
            addView(label("A10VM", 25f, ink).apply {
                setTypeface(typeface, Typeface.BOLD)
                setPadding(dp(12), 0, 0, 0)
            }, LinearLayout.LayoutParams(0, -2, 1f))
            addView(label("我的空间", 12f, muted))
        }
        column.addView(header, LinearLayout.LayoutParams(-1, dp(54)).apply { bottomMargin = dp(24) })
        val hero = card(24).apply {
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(30, 57, 49), Color.rgb(21, 35, 35))).apply { cornerRadius = dp(28).toFloat() }
            addView(status, LinearLayout.LayoutParams(-2, -2))
            val intro = LinearLayout(context).apply {
                gravity = Gravity.CENTER_VERTICAL
                addView(LinearLayout(context).apply {
                    orientation = LinearLayout.VERTICAL
                    addView(label("Android 10", 32f, ink).apply { setTypeface(typeface, Typeface.BOLD) })
                    addView(label("桌面与应用，随时进入。", 13f, muted).apply { setPadding(0, dp(8), 0, 0) })
                }, LinearLayout.LayoutParams(0, -2, 1f))
                addView(ImageView(context).apply {
                    setImageResource(R.drawable.ic_workspace)
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }, LinearLayout.LayoutParams(dp(90), dp(104)))
            }
            addView(intro, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12); bottomMargin = dp(12) })
            addView(detail, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(18) })
            addView(start, LinearLayout.LayoutParams(-1, dp(56)))
            addView(fullscreen, LinearLayout.LayoutParams(-1, dp(56)))
            addView(progress, LinearLayout.LayoutParams(-1, dp(3)).apply { topMargin = dp(14) })
        }
        column.addView(hero, LinearLayout.LayoutParams(-1, -2))
        section("应用与文件", "添加应用，导入手机里的文件", listOf(install, importFiles))
        section("相机、声音与网络", "让 Android 10 里的应用使用手机设备", listOf(microphone, camera, wifi))
        section("检查与管理", null, listOf(inspect, desktop, stop, logs))
        column.addView(label("A10VM · Android 10", 11f, muted).apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(26), 0, 0)
        })
    }

    fun render(state: String, message: String, busy: Boolean) {
        val running = state == "RUNNING"
        val text = when (state) { "RUNNING" -> "● 运行中"; "BUSY" -> "● 正在准备"; "ERROR" -> "● 操作未完成"; else -> "● 可以启动" }
        status.text = text
        status.setTextColor(when (state) { "BUSY" -> Color.rgb(246, 210, 140); "ERROR" -> Color.rgb(245, 169, 153); else -> mint })
        detail.text = when {
            state == "ERROR" -> "这次操作未完成。请重试，或查看运行记录了解原因。"
            message.startsWith("Android 10 系统服务已启动") -> "桌面已准备好，可以继续使用应用。"
            message.startsWith("正在启动 Android 10") -> "正在准备桌面与应用，请稍候…"
            message.startsWith("Android 10 桌面、ART") -> "运行环境检查通过，可以启动 Android 10。"
            message.startsWith("Android 10 系统服务及 Launcher3") -> "启动测试完成，桌面可以正常打开。"
            message.startsWith("正在检查 Android 10 桌面启动") -> "正在测试桌面能否启动，请稍候…"
            message == "正在处理原生显示操作。" -> "正在检查运行环境，请稍候…"
            else -> message
        }
        progress.visibility = if (busy) View.VISIBLE else View.GONE
        start.visibility = if (running) View.GONE else View.VISIBLE
        fullscreen.visibility = if (running) View.VISIBLE else View.GONE
        listOf(inspect, desktop, start).forEach { enable(it, !busy && !running) }
        listOf(stop, fullscreen, install, importFiles).forEach { enable(it, !busy && running) }
        if (state != renderedState && isShown && ValueAnimator.areAnimatorsEnabled()) {
            status.animate().cancel()
            status.alpha = .4f
            status.animate().alpha(1f).setDuration(220).start()
        }
        renderedState = state
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (entered || !ValueAnimator.areAnimatorsEnabled()) return
        entered = true
        for (index in 0 until column.childCount) {
            column.getChildAt(index).apply {
                alpha = 0f
                translationY = dp(12).toFloat()
                animate().alpha(1f).translationY(0f).setStartDelay(index * 35L)
                    .setDuration(300).setInterpolator(DecelerateInterpolator()).start()
            }
        }
    }

    private fun section(title: String, subtitle: String?, buttons: List<Button>) {
        column.addView(label(title, 17f, ink).apply {
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(2), dp(26), 0, dp(6))
        })
        if (subtitle != null) column.addView(label(subtitle, 12f, muted).apply { setPadding(dp(2), 0, 0, dp(12)) })
        column.addView(card(8).apply {
            buttons.forEachIndexed { index, button ->
                addView(button, LinearLayout.LayoutParams(-1, dp(52)).apply { if (index > 0) topMargin = dp(4) })
            }
        }, LinearLayout.LayoutParams(-1, -2))
    }

    private fun action(title: String, primary: Boolean = false) = object : Button(context) {
        override fun performClick(): Boolean {
            if (isEnabled) performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
            return super.performClick()
        }
    }.apply {
        text = title
        textSize = if (primary) 16f else 14f
        isAllCaps = false
        gravity = if (primary) Gravity.CENTER else Gravity.CENTER_VERTICAL or Gravity.START
        setTextColor(if (primary) Color.rgb(15, 45, 34) else ink)
        if (primary) setTypeface(typeface, Typeface.BOLD)
        setPadding(dp(18), 0, dp(18), 0)
        minWidth = 0
        minHeight = dp(48)
        background = RippleDrawable(ColorStateList.valueOf(Color.argb(40, 255, 255, 255)),
            shape(if (primary) mint else Color.rgb(26, 42, 43), if (primary) 18 else 14), null)
        val button = this
        stateListAnimator = StateListAnimator().apply {
            fun scale(value: Float) = AnimatorSet().apply {
                playTogether(ObjectAnimator.ofFloat(button, "scaleX", value),
                    ObjectAnimator.ofFloat(button, "scaleY", value))
                duration = 130
            }
            addState(intArrayOf(android.R.attr.state_pressed), scale(.975f))
            addState(intArrayOf(), scale(1f))
        }
    }

    private fun enable(view: View, enabled: Boolean) { view.isEnabled = enabled; view.alpha = if (enabled) 1f else .4f }
    private fun card(padding: Int) = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(padding), dp(padding), dp(padding), dp(padding))
        background = shape(Color.rgb(20, 33, 35), 22)
    }
    private fun label(text: String, size: Float, color: Int) = TextView(context).apply {
        this.text = text; textSize = size; setTextColor(color)
    }
    private fun shape(color: Int, radius: Int) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun dp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()
}
