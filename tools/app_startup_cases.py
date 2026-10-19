"""Explicit guest launch intents shared by startup and in-app performance measurements."""

CASES = {
    "miui-home": ("com.miui.home", ["-a", "android.intent.action.MAIN", "-c",
        "android.intent.category.HOME", "-p", "com.miui.home"]),
    "settings": ("com.android.settings", ["-a", "android.settings.SETTINGS"]),
    "miui-market": ("com.xiaomi.market", ["-n", "com.xiaomi.market/.ui.MarketTabActivity"]),
    "mt": ("bin.mt.plus", ["-n", "bin.mt.plus/.MainLightIcon"]),
    "qq": ("com.tencent.mobileqq", ["-n", "com.tencent.mobileqq/.activity.SplashActivity"]),
    "wechat": ("com.tencent.mm", ["-n", "com.tencent.mm/.ui.LauncherUI"]),
    "douyin": ("com.ss.android.ugc.aweme", ["-n", "com.ss.android.ugc.aweme/.splash.SplashActivity"]),
    "bilibili": ("tv.danmaku.bili", ["-a", "android.intent.action.MAIN", "-c",
        "android.intent.category.LAUNCHER", "-p", "tv.danmaku.bili"]),
}
