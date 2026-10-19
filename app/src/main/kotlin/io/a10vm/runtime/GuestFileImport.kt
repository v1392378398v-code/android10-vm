package io.a10vm.runtime

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import org.json.JSONArray

internal class GuestFileImport(private val context: Context) {
    fun importFiles(uris: JSONArray, session: NativeGraphicsSession): String {
        val directory = File(context.filesDir, "guest-runtime/rootfs/storage/emulated/0/Download")
        check(directory.mkdirs() || directory.isDirectory) { "客体下载目录创建失败" }
        val imported = mutableListOf<String>()
        for (index in 0 until uris.length()) {
            val uri = Uri.parse(uris.getString(index))
            var name = "import-${System.currentTimeMillis()}-$index"
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) name = cursor.getString(0) ?: name
            }
            name = name.map { if (it == '/' || it == '\\' || it.code < 32) '_' else it }
                .joinToString("").take(180).ifBlank { "import-$index" }
            var target = File(directory, name)
            var suffix = 1
            while (target.exists()) target = File(directory, "${suffix++}-$name")
            val temporary = File.createTempFile(".import-", ".part", directory)
            try {
                context.contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "读取文件失败：$name" }
                    temporary.outputStream().use { output -> input.copyTo(output) }
                }
                check(temporary.renameTo(target)) { "保存客体文件失败：$name" }
                val guest = "/storage/emulated/0/Download/${target.name}"
                session.scanMedia(guest)
                imported += target.name
            } finally { temporary.delete() }
        }
        return "已导入 Android 10 下载目录，图片和视频可在图库中查看：\n${imported.joinToString("\n")}"
    }
}
