package io.a10vm.ui

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import java.text.Collator
import java.util.Locale
import java.util.concurrent.Executors

internal class InstalledAppsDialog(
    private val activity: Activity,
    private val onImport: (List<String>) -> Unit,
) {
    private data class App(val info: ApplicationInfo, val label: String)
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val selected = linkedSetOf<String>()
    private var applications = emptyList<App>()
    private var visible = emptyList<App>()
    private var closed = false
    private val search = EditText(activity).apply {
        hint = "搜索应用名称或包名"
        setSingleLine(true)
    }
    private val status = TextView(activity).apply {
        text = "正在读取手机上的应用…"
        setPadding(0, dp(8), 0, dp(8))
    }
    private val adapter = object : BaseAdapter() {
        override fun getCount() = visible.size
        override fun getItem(position: Int) = visible[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val row = convertView as? LinearLayout ?: LinearLayout(activity).apply {
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(4), dp(8), dp(4), dp(8))
                addView(ImageView(activity), LinearLayout.LayoutParams(dp(40), dp(40)))
                addView(CheckedTextView(activity).apply {
                    setPadding(dp(12), 0, 0, 0)
                    val style = activity.obtainStyledAttributes(intArrayOf(android.R.attr.listChoiceIndicatorMultiple))
                    checkMarkDrawable = style.getDrawable(0)
                    style.recycle()
                    textSize = 15f
                }, LinearLayout.LayoutParams(0, -2, 1f))
            }
            val app = getItem(position)
            (row.getChildAt(0) as ImageView).setImageDrawable(
                try { app.info.loadIcon(activity.packageManager) }
                catch (_: RuntimeException) { activity.packageManager.defaultActivityIcon })
            (row.getChildAt(1) as CheckedTextView).apply {
                text = "${app.label}\n${app.info.packageName}"
                isChecked = app.info.packageName in selected
            }
            return row
        }
    }
    private val list = ListView(activity).apply {
        adapter = this@InstalledAppsDialog.adapter
        setOnItemClickListener { _, _, position, _ ->
            val name = visible[position].info.packageName
            if (!selected.add(name)) selected.remove(name)
            refreshSelection()
            this@InstalledAppsDialog.adapter.notifyDataSetChanged()
        }
    }
    private val dialog = AlertDialog.Builder(activity).setTitle("选择手机上的应用")
        .setView(LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), 0)
            addView(search)
            addView(TextView(activity).apply {
                text = "支持多选。仅导入应用，应用数据需在 Android 10 内重新设置。"
                textSize = 13f
                setPadding(0, dp(8), 0, 0)
            })
            addView(status)
            addView(list, LinearLayout.LayoutParams(-1, 0, 1f))
        }).setNegativeButton("取消", null).setPositiveButton("导入", null).create()

    fun show() {
        dialog.setOnDismissListener {
            closed = true
            worker.shutdownNow()
            main.removeCallbacksAndMessages(null)
        }
        dialog.show()
        dialog.window?.setLayout(-1, (activity.resources.displayMetrics.heightPixels * 0.82f).toInt())
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            onImport(selected.toList())
            dismiss()
        }
        refreshSelection()
        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { filter() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        worker.execute {
            try {
                val pm = activity.packageManager
                @Suppress("DEPRECATION")
                val launchable = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_LAUNCHER), 0).map { it.activityInfo.packageName }.toSet()
                val collator = Collator.getInstance(Locale.CHINA)
                @Suppress("DEPRECATION")
                val loaded = pm.getInstalledApplications(0).filter {
                    it.packageName != activity.packageName && it.flags and ApplicationInfo.FLAG_HAS_CODE != 0 &&
                        (it.flags and ApplicationInfo.FLAG_SYSTEM == 0 ||
                            it.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0 || it.packageName in launchable)
                }.map { App(it, it.loadLabel(pm).toString()) }
                    .sortedWith { a, b -> collator.compare(a.label, b.label) }
                main.post { if (!closed) { applications = loaded; filter() } }
            } catch (_: Exception) {
                main.post { if (!closed) status.text = "读取应用列表失败，请关闭后重试" }
            }
        }
    }

    private fun filter() {
        val query = search.text.toString().trim()
        visible = applications.filter { it.label.contains(query, true) || it.info.packageName.contains(query, true) }
        status.text = if (visible.isEmpty()) "没有找到应用" else "共 ${visible.size} 个应用，已选 ${selected.size} 个"
        adapter.notifyDataSetChanged()
    }

    private fun refreshSelection() {
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).apply {
            isEnabled = selected.isNotEmpty()
            text = if (selected.isEmpty()) "导入" else "导入（${selected.size}）"
        }
        if (applications.isNotEmpty()) status.text = "共 ${visible.size} 个应用，已选 ${selected.size} 个"
    }

    fun dismiss() { dialog.dismiss() }
    private fun dp(value: Int) = (activity.resources.displayMetrics.density * value).toInt()
}
