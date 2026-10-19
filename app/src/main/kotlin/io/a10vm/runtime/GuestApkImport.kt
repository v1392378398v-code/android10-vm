package io.a10vm.runtime

import android.content.Context
import android.net.Uri
import java.io.File
import org.json.JSONArray

internal class GuestApkImport(private val context: Context) {
    fun importInstalled(packages: JSONArray, session: NativeGraphicsSession, progress: (String) -> Unit): String {
        val names = (0 until packages.length()).map { packages.getString(it) }.distinct()
        require(names.isNotEmpty()) { "请先选择应用" }
        val results = mutableListOf<String>()
        var installed = 0
        for ((index, name) in names.withIndex()) {
            var label = name
            val directory = File(context.filesDir, "guest-imports").apply { mkdirs() }
            val temporary = java.nio.file.Files.createTempDirectory(directory.toPath(), "app-").toFile()
            try {
                @Suppress("DEPRECATION")
                val info = context.packageManager.getApplicationInfo(name, 0)
                label = info.loadLabel(context.packageManager).toString()
                progress("正在导入 ${index + 1}/${names.size}：$label")
                require(info.minSdkVersion <= 29) { "此版本要求 API ${info.minSdkVersion}，请选择兼容 Android 10 的版本" }
                val sources = listOf(info.sourceDir) + info.splitSourceDirs.orEmpty().toList()
                val apks = sources.mapIndexed { part, path ->
                    File(path).copyTo(File(temporary, if (part == 0) "base.apk" else "split-$part.apk"))
                }
                session.installApks(apks)
                installed++
                results += "$label：已导入"
            } catch (failure: Exception) {
                android.util.Log.w("A10VM_NATIVE", "Import $name", failure)
                val message = failure.message.orEmpty()
                val reason = Regex("Failure \\[([^]]+)]").find(message)?.groupValues?.get(1)
                    ?: message.lineSequence().firstOrNull { it.isNotBlank() }.orEmpty().take(180)
                results += "$label：$reason"
            } finally { temporary.deleteRecursively() }
        }
        return "已导入 $installed/${names.size} 个应用，可在 Android 10 桌面打开。\n${results.joinToString("\n")}"
    }

    fun install(uri: Uri, session: NativeGraphicsSession): String {
        val directory = File(context.filesDir, "guest-imports").apply { mkdirs() }
        val apk = File.createTempFile("import-", ".apk", directory)
        try {
            context.contentResolver.openInputStream(uri).use { input ->
                requireNotNull(input) { "读取 APK 失败" }
                apk.outputStream().use { output -> input.copyTo(output) }
            }
            @Suppress("DEPRECATION")
            val info = context.packageManager.getPackageArchiveInfo(apk.path, 0)
            requireNotNull(info) { "请选择完整 APK 文件" }
            val output = session.installApk(apk)
            return "${info.packageName} 已安装到 Android 10，进入桌面应用抽屉即可打开。\n$output"
        } finally {
            apk.delete()
        }
    }
}
