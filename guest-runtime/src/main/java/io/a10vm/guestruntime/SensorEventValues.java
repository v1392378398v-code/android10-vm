package io.a10vm.guestruntime;

import java.util.Arrays;

/** Values encoded by the Android 10 Sensors HAL bridge. */
final class SensorEventValues {
    static float[] copy(int type, float[] values) {
        // DEVICE_ORIENTATION is a Surface rotation index, not an angle or vendor posture.
        if (type == 27 && (values.length == 0 || !Float.isFinite(values[0]) ||
                values[0] < 0 || values[0] > 3 || values[0] != (int) values[0])) return null;
        return Arrays.copyOf(values, Math.min(16, values.length));
    }
}
