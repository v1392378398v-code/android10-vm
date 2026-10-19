package io.a10vm.guestruntime;

public final class SensorEventValuesTest {
    public static void main(String[] args) {
        for (float rotation : new float[] {0, 1, 2, 3}) {
            float[] source = {rotation};
            float[] copy = SensorEventValues.copy(27, source);
            if (copy == null || copy == source || copy[0] != rotation)
                throw new AssertionError("Valid device orientation lost: " + rotation);
        }
        for (float rotation : new float[] {-1, 4, 90, 1.5f, Float.NaN,
                Float.NEGATIVE_INFINITY, Float.POSITIVE_INFINITY}) {
            if (SensorEventValues.copy(27, new float[] {rotation}) != null)
                throw new AssertionError("Invalid device orientation relayed: " + rotation);
        }
        if (SensorEventValues.copy(27, new float[0]) != null)
            throw new AssertionError("Empty device orientation relayed");
        float[] acceleration = {4, -1, 9.8f};
        float[] copy = SensorEventValues.copy(1, acceleration);
        if (copy == acceleration || !java.util.Arrays.equals(copy, acceleration))
            throw new AssertionError("Non-orientation event changed");
        if (SensorEventValues.copy(11, new float[20]).length != 16)
            throw new AssertionError("Sensor protocol value limit changed");
        System.out.println("sensor_event_values_complete=1");
    }
}
