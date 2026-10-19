package io.a10vm.ui

import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.view.animation.LinearInterpolator
import android.widget.*
import io.a10vm.R

/** A finite boot session owns the animation; hidden windows never keep it running. */
class BootAnimationView(context: Context, onLogs: () -> Unit) : FrameLayout(context) {
    private val mint = Color.rgb(114, 226, 185)
    private val orbit = Orbit(context)
    private val terminal = BootTerminalView(context)
    private val stage = label("正在准备启动…", 14f, Color.rgb(180, 206, 196))
    private val elapsed = label("已等待 0 秒", 13f, Color.rgb(155, 177, 170))
    private var orbitAnimator: ObjectAnimator? = null
    private var started = 0L
    private var logSession = ""
    private var logSequence = 0L
    private var ticking = false
    private val tick = object : Runnable {
        override fun run() {
            if (!isShown || !hasWindowFocus() || windowVisibility != View.VISIBLE) { ticking = false; return }
            elapsed.text = "已等待 ${(SystemClock.elapsedRealtime() - started) / 1000} 秒"
            postDelayed(this, 1000)
        }
    }

    init {
        visibility = View.GONE
        isClickable = true
        background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(Color.rgb(12, 21, 23), Color.rgb(20, 43, 34)))
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(20), dp(24), dp(20))
            addView(label("A10VM", 25f, Color.rgb(235, 245, 241)).apply {
                setTypeface(typeface, android.graphics.Typeface.BOLD)
            })
            addView(FrameLayout(context).apply {
                addView(orbit, LayoutParams(-1, -1))
                addView(ImageView(context).apply {
                    setImageResource(R.drawable.ic_launcher)
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }, LayoutParams(dp(50), dp(50), Gravity.CENTER))
            }, LinearLayout.LayoutParams(dp(if (resources.configuration.screenHeightDp < 560) 76 else 128),
                dp(if (resources.configuration.screenHeightDp < 560) 76 else 128)).apply {
                topMargin = dp(8); bottomMargin = dp(4)
            })
            addView(label("正在启动 Android 10", 19f, Color.rgb(235, 245, 241)))
            addView(stage.apply { setPadding(0, dp(8), 0, 0); maxLines = 1 })
            addView(elapsed.apply { setPadding(0, dp(8), 0, 0) })
            addView(terminal, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = dp(20); bottomMargin = dp(10) })
            addView(label("开机记录会自动向上滚动", 11f, Color.rgb(155, 177, 170)))
        }
        content.addView(Button(context).apply {
            text = "查看详细记录"
            textSize = 14f
            isAllCaps = false
            setTextColor(mint)
            background = RippleDrawable(ColorStateList.valueOf(Color.argb(30, 114, 226, 185)),
                GradientDrawable().apply { setColor(Color.rgb(25, 51, 40)); cornerRadius = dp(18).toFloat() }, null)
            setOnClickListener { onLogs() }
        }, LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(12) })
        addView(content, LayoutParams(-1, -1))
        setOnApplyWindowInsetsListener { view, insets ->
            val bars = SystemUi.insets(insets)
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
    }

    fun setBooting(active: Boolean) {
        if ((visibility == View.VISIBLE) == active) return
        if (active) {
            started = SystemClock.elapsedRealtime(); elapsed.text = "已等待 0 秒"
            stage.text = "正在准备启动…"
            logSession = ""; logSequence = 0; terminal.clear()
        }
        visibility = if (active) View.VISIBLE else View.GONE
        syncMotion()
    }

    fun showLog(session: String, sequence: Long, elapsedMillis: Long, lines: List<String>) {
        if (visibility != View.VISIBLE || session.isEmpty()) return
        if (session != logSession) {
            logSession = session; logSequence = 0; terminal.clear()
            started = SystemClock.elapsedRealtime() - elapsedMillis
        }
        if (sequence <= logSequence) return
        lines.lastOrNull()?.let { stage.text = BootLogText.message(it) }
        val unseen = (sequence - logSequence).coerceAtMost(lines.size.toLong()).toInt()
        terminal.append(lines.takeLast(unseen))
        logSequence = sequence
    }

    override fun onAttachedToWindow() { super.onAttachedToWindow(); syncMotion() }
    override fun onDetachedFromWindow() { stopMotion(); super.onDetachedFromWindow() }
    override fun onWindowVisibilityChanged(visibility: Int) {
        super.onWindowVisibilityChanged(visibility)
        if (isAttachedToWindow) syncMotion()
    }
    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        if (isAttachedToWindow) syncMotion()
    }
    override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
        super.onWindowFocusChanged(hasWindowFocus)
        if (isAttachedToWindow) syncMotion()
    }

    private fun syncMotion() {
        if (!isAttachedToWindow || !isShown || !hasWindowFocus() || windowVisibility != View.VISIBLE) { stopMotion(); return }
        if (!ticking) { ticking = true; post(tick) }
        terminal.setActive(true)
        if (orbitAnimator == null && ValueAnimator.areAnimatorsEnabled()) {
            orbitAnimator = ObjectAnimator.ofFloat(orbit, View.ROTATION, orbit.rotation, orbit.rotation + 360f).apply {
                duration = 4200
                repeatCount = ValueAnimator.INFINITE
                interpolator = LinearInterpolator()
                start()
            }
        }
    }
    private fun stopMotion() {
        orbitAnimator?.cancel(); orbitAnimator = null; removeCallbacks(tick); ticking = false
        terminal.setActive(false)
    }
    private fun label(text: String, size: Float, color: Int) = TextView(context).apply {
        this.text = text; textSize = size; setTextColor(color); gravity = Gravity.CENTER
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()

    private class Orbit(context: Context) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        init { setLayerType(View.LAYER_TYPE_HARDWARE, null); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }
        override fun onDraw(canvas: Canvas) {
            val cx = width / 2f
            val cy = height / 2f
            val radius = width * .37f
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = resources.displayMetrics.density
            paint.color = Color.rgb(43, 78, 61)
            canvas.drawCircle(cx, cy, radius, paint)
            canvas.drawCircle(cx, cy, radius * .8f, paint)
            paint.strokeWidth *= 2
            paint.strokeCap = Paint.Cap.ROUND
            paint.color = Color.rgb(114, 226, 185)
            canvas.drawArc(cx - radius, cy - radius, cx + radius, cy + radius, -90f, 80f, false, paint)
            paint.style = Paint.Style.FILL
            canvas.drawCircle(cx, cy - radius, resources.displayMetrics.density * 4, paint)
            paint.color = Color.rgb(221, 235, 180)
            canvas.drawCircle(cx, cy + radius, resources.displayMetrics.density * 3, paint)
        }
    }
}
