package io.a10vm.ui

/** User-facing progress stays separate from the original diagnostic events. */
internal object BootLogText {
    private val components = mapOf(
        "properties" to "系统设置", "broker" to "系统通信", "manager" to "系统服务",
        "hwbroker" to "设备通信", "hwmanager" to "设备管理", "gpu" to "图形显示",
        "suspend" to "省电功能", "composer" to "画面显示", "allocator" to "画面内存",
        "configstore" to "显示设置", "keymaster" to "应用密钥", "keystore" to "应用密钥",
        "health" to "电量信息", "idmap" to "界面资源", "host-devices" to "设备连接",
        "camera-provider" to "相机连接", "camera" to "相机功能", "audio-hal" to "声音连接",
        "audio" to "声音功能", "installer" to "应用安装功能", "rom-shelld" to "系统工具",
        "rom-fdpp" to "系统组件", "compositor" to "画面合成", "server" to "Android 系统",
        "client" to "桌面和应用", "input" to "触摸操作",
    )

    fun message(line: String): String {
        val event = line.substringAfter("] ").trim().split(Regex("\\s+"), limit = 2)
        val detail = event.getOrElse(1) { "" }
        val component = detail.substringBefore(':').substringBefore(' ')
        val name = components[component] ?: if (component.startsWith("media")) "音视频功能" else "系统组件"
        return when (event[0]) {
            "BOOT" -> "开始启动 Android 10"
            "VERIFY" -> if (detail.startsWith("runtime files "))
                "正在检查系统文件：${detail.substringAfter("runtime files ")}" else "正在检查启动环境"
            "DATA" -> "正在准备系统文件：${detail.substringAfter("image files ")}"
            "PREPARE" -> "正在准备应用和文件"
            "SHMEM" -> "运行所需的内存已准备好"
            "ART" -> if (detail.startsWith("Checking")) "正在检查应用运行环境" else "应用运行环境检查完成"
            "DEVICES" -> "设备连接已准备好"
            "GPU" -> "画面已准备好，正在启动桌面"
            "SPAWN" -> "正在启动$name"
            "READY" -> if (detail.startsWith("Android desktop")) "桌面已准备好，即将进入" else "${name}已准备好"
            "WAIT" -> "正在等待${name}准备完成"
            "ERROR" -> "启动遇到问题，请查看详细记录"
            else -> "正在准备系统"
        }
    }

    fun format(line: String): String = line.substringBefore(']').replace("s", " 秒") + "] " + message(line)
}
