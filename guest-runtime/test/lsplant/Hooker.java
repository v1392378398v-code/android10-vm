package com.hooker.lsplant;

import java.lang.reflect.Method;

public final class Hooker {
    public native Method doHook(Method target, Method callback);
    public native boolean doUnhook(Method target);

    public Object callback(Object[] arguments) {
        return 42;
    }
}
