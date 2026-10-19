package io.a10vm.containerprobe;

import org.json.JSONException;
import org.json.JSONObject;

/** Matches WindowRenderer::Metric; all times use the monotonic clock. */
final class WindowSnapshot {
    final long ready, frames, swaps, inputSequence, echoSequence, presentedFrame;
    final long requestedGeneration, boundGeneration, inputNanos, submitNanos, inputSubmitNanos;
    final long pid, uid, done, dropped, euid, presentedGeneration;

    WindowSnapshot(long[] v) {
        if (v.length != 17) throw new IllegalStateException("Window metric ABI mismatch");
        ready = v[0]; frames = v[1]; swaps = v[2]; inputSequence = v[3]; echoSequence = v[4];
        presentedFrame = v[5]; requestedGeneration = v[6]; boundGeneration = v[7];
        inputNanos = v[8]; submitNanos = v[9]; inputSubmitNanos = v[10];
        pid = v[11]; uid = v[12]; done = v[13]; dropped = v[14]; euid = v[15];
        presentedGeneration = v[16];
    }

    JSONObject json() throws JSONException {
        return new JSONObject().put("frames", frames).put("swaps", swaps)
                .put("inputSequence", inputSequence).put("echoSequence", echoSequence)
                .put("presentedFrame", presentedFrame).put("requestedGeneration", requestedGeneration)
                .put("boundGeneration", boundGeneration).put("presentedGeneration", presentedGeneration)
                .put("inputNanos", inputNanos).put("submitNanos", submitNanos)
                .put("inputSubmitNanos", inputSubmitNanos).put("pid", pid).put("uid", uid)
                .put("euid", euid).put("done", done).put("dropped", dropped);
    }
}
