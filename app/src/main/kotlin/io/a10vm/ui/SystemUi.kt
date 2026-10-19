package io.a10vm.ui

import android.os.Build
import android.view.View
import android.view.Window
import android.view.WindowInsets
import android.view.WindowInsetsController

/** The same layouts use public window APIs on Android 9 and later. */
internal object SystemUi {
    data class Insets(val left: Int, val top: Int, val right: Int, val bottom: Int)

    @Suppress("DEPRECATION")
    fun insets(value: WindowInsets, includeHiddenBars: Boolean = false): Insets {
        if (Build.VERSION.SDK_INT >= 30) {
            val types = WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout()
            val bars = if (includeHiddenBars) value.getInsetsIgnoringVisibility(types) else value.getInsets(types)
            return Insets(bars.left, bars.top, bars.right, bars.bottom)
        }
        val cutout = value.displayCutout
        return Insets(
            maxOf(if (includeHiddenBars) value.stableInsetLeft else value.systemWindowInsetLeft, cutout?.safeInsetLeft ?: 0),
            maxOf(if (includeHiddenBars) value.stableInsetTop else value.systemWindowInsetTop, cutout?.safeInsetTop ?: 0),
            maxOf(if (includeHiddenBars) value.stableInsetRight else value.systemWindowInsetRight, cutout?.safeInsetRight ?: 0),
            maxOf(if (includeHiddenBars) value.stableInsetBottom else value.systemWindowInsetBottom, cutout?.safeInsetBottom ?: 0),
        )
    }

    @Suppress("DEPRECATION")
    fun darkBars(window: Window) {
        if (Build.VERSION.SDK_INT >= 30) window.insetsController?.setSystemBarsAppearance(0,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS)
        else window.decorView.systemUiVisibility = window.decorView.systemUiVisibility and
            (View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR).inv()
    }

    @Suppress("DEPRECATION")
    fun fullscreen(window: Window) {
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.apply {
                systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                hide(WindowInsets.Type.systemBars())
            }
        } else window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
    }
}
