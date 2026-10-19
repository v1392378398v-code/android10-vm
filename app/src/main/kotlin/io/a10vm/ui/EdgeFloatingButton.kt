package io.a10vm.ui

import android.content.Context
import android.graphics.Color
import android.graphics.Rect
import android.os.Build
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.view.animation.DecelerateInterpolator
import android.widget.Button

class EdgeFloatingButton(context: Context) : Button(context) {
    private val preferences = context.getSharedPreferences("floating_management", Context.MODE_PRIVATE)
    private val area = Rect()
    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
    private var dockRight = preferences.getBoolean("dock_right", true)
    private var heightRatio = preferences.getFloat("height_ratio", .15f).coerceIn(0f, 1f)
    private var downX = 0f
    private var downY = 0f
    private var startX = 0f
    private var startY = 0f
    private var dragging = false

    val buttonSize: Int = dp(48)

    init {
        text = "管理"
        contentDescription = "打开管理页，可拖动贴边"
        textSize = 12f
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        minWidth = 0
        minHeight = 0
        includeFontPadding = false
        setPadding(0, 0, 0, 0)
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.rgb(35, 48, 65))
            setStroke(dp(1), Color.argb(100, 255, 255, 255))
        }
        elevation = dp(6).toFloat()
        alpha = .75f
    }

    fun setSafeArea(left: Int, top: Int, right: Int, bottom: Int) {
        area.set(left, top, right.coerceAtLeast(left), bottom.coerceAtLeast(top))
        if (!dragging) dock(animate = false)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (Build.VERSION.SDK_INT >= 29) systemGestureExclusionRects = listOf(Rect(0, 0, w, h))
        dock(animate = false)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                animate().cancel()
                downX = event.x + x
                downY = event.y + y
                startX = x
                startY = y
                dragging = false
                isPressed = true
                alpha = .95f
                parent?.requestDisallowInterceptTouchEvent(true)
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.x + x - downX
                val dy = event.y + y - downY
                if (dx * dx + dy * dy > touchSlop * touchSlop) dragging = true
                if (dragging) {
                    isPressed = false
                    moveTo(event)
                }
            }
            MotionEvent.ACTION_UP -> {
                isPressed = false
                alpha = .75f
                parent?.requestDisallowInterceptTouchEvent(false)
                if (dragging) {
                    moveTo(event)
                    dockRight = x + width / 2f >= area.exactCenterX()
                    val travel = maxY() - area.top
                    heightRatio = if (travel > 0) (y - area.top) / travel else 0f
                    preferences.edit().putBoolean("dock_right", dockRight)
                        .putFloat("height_ratio", heightRatio).apply()
                    dragging = false
                    dock(animate = true)
                } else {
                    performClick()
                }
            }
            MotionEvent.ACTION_CANCEL -> {
                isPressed = false
                alpha = .75f
                dragging = false
                parent?.requestDisallowInterceptTouchEvent(false)
                dock(animate = true)
            }
        }
        return true
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun dock(animate: Boolean) {
        if (width == 0 || height == 0 || area.isEmpty) return
        val targetX = if (dockRight) maxX() else area.left.toFloat()
        val targetY = area.top + (maxY() - area.top) * heightRatio
        this.animate().cancel()
        if (animate) {
            this.animate().x(targetX).y(targetY).setDuration(180)
                .setInterpolator(DecelerateInterpolator()).start()
        } else {
            x = targetX
            y = targetY
        }
    }

    private fun maxX() = (area.right - width).coerceAtLeast(area.left).toFloat()
    private fun maxY() = (area.bottom - height).coerceAtLeast(area.top).toFloat()
    private fun moveTo(event: MotionEvent) {
        x = (startX + event.x + x - downX).coerceIn(area.left.toFloat(), maxX())
        y = (startY + event.y + y - downY).coerceIn(area.top.toFloat(), maxY())
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()
}
