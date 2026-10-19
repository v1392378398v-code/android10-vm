package io.a10vm.guest;

import java.util.Arrays;
import java.util.List;

public final class AppRuntimeOptionsCheck {
    public static void main(String[] args) {
        List<String> expected = Arrays.asList("-Xcompiler-option", "--inline-max-code-units=0");
        for (String name : new String[] {"com.ss.android.ugc.aweme", "com.ss.android.ugc.aweme:push",
                "com.ss.android.ugc.aweme:download"}) {
            if (!expected.equals(AppRuntimeOptions.forProcess(name)))
                throw new AssertionError("Missing JIT compatibility options for " + name);
        }
        for (String name : new String[] {"com.android.launcher3", "com.android.webview", "com.tencent.mobileqq",
                "com.ss.android.ugc.aweme.lite", "com.ss.android.ugc.awemeX", "guest-application", ""}) {
            if (!AppRuntimeOptions.forProcess(name).isEmpty())
                throw new AssertionError("Unrelated process options changed: " + name);
        }
        if (expected.toString().contains("-Xint") || expected.toString().contains("-Xusejit:false"))
            throw new AssertionError("JIT compilation must remain enabled");
        System.out.println("app_runtime_options_complete=1");
    }
}
