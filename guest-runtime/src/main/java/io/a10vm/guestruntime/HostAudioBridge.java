package io.a10vm.guestruntime;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.AudioTimestamp;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.net.LocalSocket;
import android.util.Log;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;

/** PCM transport for the guest audio HAL, using ordinary host audio APIs. */
public final class HostAudioBridge implements AutoCloseable {
    private final Context context;
    private final HostStreamServer server;

    public HostAudioBridge(Context context) throws IOException {
        this.context = context.getApplicationContext();
        server = new HostStreamServer(context, "audio", this::serve);
    }

    public void start() throws IOException { server.start(); }
    @Override public void close() { server.close(); }

    private void serve(LocalSocket socket) throws Exception {
        DataInputStream input = new DataInputStream(socket.getInputStream());
        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
        if (input.readInt() != 0x41313041 || input.readInt() != 1) throw new IOException("Audio protocol");
        boolean capture = input.readInt() == 1;
        int rate = input.readInt(), channels = input.readInt(), encoding = input.readInt(), requested = input.readInt();
        AudioTrack track = null;
        AudioRecord record = null;
        try {
            if (rate < 8000 || rate > 192000 || channels < 1 || channels > 2 || requested <= 0 || requested > 65536 ||
                    (encoding != AudioFormat.ENCODING_PCM_16BIT && encoding != AudioFormat.ENCODING_PCM_FLOAT &&
                     encoding != AudioFormat.ENCODING_PCM_8BIT)) {
                output.writeInt(-22); output.flush(); return;
            }
            if (capture && context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                output.writeInt(-13); output.flush(); return;
            }
            int mask = capture ? (channels == 1 ? AudioFormat.CHANNEL_IN_MONO : AudioFormat.CHANNEL_IN_STEREO) :
                    (channels == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO);
            int minimum = capture ? AudioRecord.getMinBufferSize(rate, mask, encoding) : AudioTrack.getMinBufferSize(rate, mask, encoding);
            if (minimum <= 0) { output.writeInt(-22); output.flush(); return; }
            AudioFormat format = new AudioFormat.Builder().setSampleRate(rate).setChannelMask(mask).setEncoding(encoding).build();
            int capacity = Math.max(minimum, requested * 4);
            if (capture) {
                record = new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.MIC)
                        .setAudioFormat(format).setBufferSizeInBytes(capacity).build();
                if (record.getState() != AudioRecord.STATE_INITIALIZED) throw new IOException("Host audio input initialization");
                record.startRecording();
                if (record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IOException("Host recording did not start");
            } else {
                track = new AudioTrack.Builder().setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                        .setAudioFormat(format).setBufferSizeInBytes(capacity).setTransferMode(AudioTrack.MODE_STREAM).build();
                if (track.getState() != AudioTrack.STATE_INITIALIZED) throw new IOException("Host audio output initialization");
                track.play();
            }
            output.writeInt(0); output.writeInt(capacity); output.flush();
            byte[] pcm = new byte[65536];
            AudioTimestamp timestamp = new AudioTimestamp();
            long headWrap = 0, lastHead = 0;
            boolean muted = false;
            while (true) {
                int command;
                try { command = input.readInt(); } catch (EOFException end) { break; }
                if (command == 1 || command == 2) {
                    int bytes = input.readInt();
                    int frameBytes = channels * (encoding == AudioFormat.ENCODING_PCM_FLOAT ? 4 : encoding == AudioFormat.ENCODING_PCM_16BIT ? 2 : 1);
                    if (bytes <= 0 || bytes > pcm.length || bytes % frameBytes != 0 || capture != (command == 2))
                        throw new IOException("Audio request size or direction");
                    int result;
                    if (capture) {
                        result = record.read(pcm, 0, bytes, AudioRecord.READ_BLOCKING);
                        if (muted && result > 0) java.util.Arrays.fill(pcm, 0, result, (byte) 0);
                    } else {
                        input.readFully(pcm, 0, bytes);
                        result = track.write(pcm, 0, bytes, AudioTrack.WRITE_BLOCKING);
                    }
                    output.writeInt(result < 0 ? (result == -3 ? -19 : -5) : result);
                    if (capture && result > 0) output.write(pcm, 0, result);
                } else if (command == 3) {
                    boolean available = capture ? record.getTimestamp(timestamp, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS :
                            track.getTimestamp(timestamp);
                    if (!available && !capture) {
                        long head = track.getPlaybackHeadPosition() & 0xffffffffL;
                        if (head < lastHead) headWrap += 1L << 32;
                        lastHead = head;
                        timestamp.framePosition = headWrap + head;
                        timestamp.nanoTime = System.nanoTime();
                        available = true;
                    }
                    output.writeInt(available ? 0 : -11);
                    if (available) { output.writeLong(timestamp.framePosition); output.writeLong(timestamp.nanoTime); }
                } else if (command == 4) {
                    float left = input.readFloat(), right = input.readFloat();
                    output.writeInt(capture ? -22 : track.setStereoVolume(left, right));
                } else if (command == 5) {
                    muted = input.readInt() != 0;
                    output.writeInt(capture ? 0 : -22);
                } else if (command == 6) {
                    if (capture) output.writeInt(-38);
                    else { track.pause(); track.flush(); track.play(); output.writeInt(0); lastHead = 0; headWrap = 0; }
                } else throw new IOException("Audio command: " + command);
                output.flush();
            }
        } catch (SecurityException error) {
            output.writeInt(-13); output.flush(); Log.w("A10VM", "Host audio permission", error);
        } catch (IllegalArgumentException | IllegalStateException error) {
            output.writeInt(-19); output.flush(); Log.w("A10VM", "Host audio device", error);
        } finally {
            if (record != null) record.release();
            if (track != null) track.release();
        }
    }
}
