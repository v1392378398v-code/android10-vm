package io.a10vm.ui

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.text.TextPaint
import android.text.TextUtils
import android.view.View
import android.view.animation.LinearInterpolator
import java.util.ArrayDeque

/** Keeps drawing and scrolling independent of boot work and service messages. */
internal class BootTerminalView(context: Context) : View(context) {
    private val density = resources.displayMetrics.density
    private val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.MONOSPACE
        textSize = 10.5f * resources.displayMetrics.scaledDensity
    }
    private val rows = ArrayDeque<String>()
    private val pending = ArrayDeque<String>()
    private val lineHeight = paint.fontSpacing * 1.4f
    private var offset = 0f
    private var active = false
    private var scroll: ValueAnimator? = null
    private val next = Runnable { advance() }

    init { contentDescription = "开机记录，自动向上滚动" }

    fun clear() {
        stop()
        rows.clear()
        pending.clear()
        invalidate()
    }

    fun append(lines: List<String>) {
        lines.forEach { if (pending.size == 48) pending.removeFirst(); pending.addLast(it) }
        if (!active || !ValueAnimator.areAnimatorsEnabled()) flush() else advance()
    }

    fun setActive(value: Boolean) {
        active = value
        if (!value || !ValueAnimator.areAnimatorsEnabled()) { stop(); flush() } else advance()
    }

    private fun addRow(line: String) {
        if (rows.size == 64) rows.removeFirst()
        rows.addLast(line)
    }

    private fun advance() {
        if (!active || scroll != null || pending.isEmpty()) return
        if (!ValueAnimator.areAnimatorsEnabled()) { flush(); return }
        removeCallbacks(next)
        addRow(pending.removeFirst())
        scroll = ValueAnimator.ofFloat(lineHeight, 0f).apply {
            duration = if (pending.size > 16) 90 else 160
            interpolator = LinearInterpolator()
            addUpdateListener { offset = it.animatedValue as Float; invalidate() }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    scroll = null
                    offset = 0f
                    if (active) postDelayed(next, 45)
                }
            })
            start()
        }
    }

    private fun stop() {
        scroll?.removeAllListeners()
        scroll?.cancel()
        scroll = null
        offset = 0f
        removeCallbacks(next)
    }

    private fun flush() {
        stop()
        while (pending.isNotEmpty()) addRow(pending.removeFirst())
        invalidate()
    }

    override fun onDetachedFromWindow() { setActive(false); super.onDetachedFromWindow() }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val pad = 14 * density
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(3, 12, 9)
        canvas.drawRoundRect(0f, 0f, width.toFloat(), height.toFloat(), pad, pad, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = density
        paint.color = Color.rgb(34, 76, 54)
        canvas.drawRoundRect(density, density, width - density, height - density, pad, pad, paint)
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(117, 244, 166)
        canvas.drawCircle(pad + 3 * density, 23 * density, 3 * density, paint)
        canvas.drawText("实时开机记录", pad + 16 * density, 27 * density, paint)
        paint.color = Color.rgb(26, 55, 40)
        canvas.drawRect(pad, 41 * density, width - pad, 42 * density, paint)
        val top = 52 * density
        val bottom = height - pad - paint.descent()
        val capacity = ((bottom - top) / lineHeight).toInt().coerceAtLeast(1)
        val visible = rows.toList().takeLast(capacity + 1)
        canvas.save()
        canvas.clipRect(pad, top, width - pad, height - pad)
        visible.forEachIndexed { index, line ->
            paint.color = if ("ERROR" in line) Color.rgb(255, 154, 128) else Color.rgb(112, 240, 158)
            paint.alpha = (100 + 155 * (index + 1) / visible.size).coerceAtMost(255)
            val text = TextUtils.ellipsize(BootLogText.format(line), paint,
                (width - 2 * pad).coerceAtLeast(1f), TextUtils.TruncateAt.END)
            canvas.drawText(text.toString(), pad, bottom - (visible.size - index - 1) * lineHeight + offset, paint)
        }
        paint.alpha = 255
        canvas.restore()
    }
}
