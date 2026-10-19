#include <hardware/audio.h>
#include <arpa/inet.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>
#include <vector>

extern "C" audio_module HAL_MODULE_INFO_SYM;

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
static void transfer(int fd, void* data, size_t bytes, bool sendData) {
    auto* cursor = static_cast<char*>(data);
    while (bytes) {
        ssize_t result = sendData ? send(fd, cursor, bytes, MSG_NOSIGNAL) : recv(fd, cursor, bytes, 0);
        require(result > 0, "PCM fixture transport");
        cursor += result;
        bytes -= result;
    }
}
static uint32_t word(int fd) {
    uint32_t value;
    transfer(fd, &value, 4, false);
    return ntohl(value);
}
static void word(int fd, uint32_t value) {
    value = htonl(value);
    transfer(fd, &value, 4, true);
}
static void serve(int listener) {
    const int16_t expected[] = {-32768, -1, 0, 32767};
    for (int i = 0; i < 6; ++i) {
        int fd = accept(listener, nullptr, nullptr);
        require(fd >= 0 && word(fd) == 0x41313041 && word(fd) == 1, "PCM fixture header");
        bool input = word(fd) != 0;
        require(word(fd) == (input ? 44100u : 48000u), "PCM sample rate");
        require(word(fd) == (input ? 1u : 2u) && word(fd) == 2, "host PCM16 negotiation");
        word(fd);
        word(fd, 0);
        word(fd, 8192);
        if (input) {
            require(word(fd) == 5 && word(fd) == 0, "input mute protocol");
            word(fd, 0);
        }
        require(word(fd) == (input ? 2u : 1u) && word(fd) == sizeof(expected), "host PCM byte count");
        if (!input) {
            int16_t actual[4];
            transfer(fd, actual, sizeof(actual), false);
            require(std::memcmp(actual, expected, sizeof(actual)) == 0, "24/32-bit output sample conversion");
        }
        word(fd, sizeof(expected));
        if (input) transfer(fd, const_cast<int16_t*>(expected), sizeof(expected), true);
        close(fd);
    }
}
int main() {
    std::setbuf(stdout, nullptr);
    try {
        char pattern[512];
        std::snprintf(pattern, sizeof(pattern), "%s/audio-pcm-XXXXXX", getenv("TMPDIR") ? getenv("TMPDIR") : ".");
        char* directory = mkdtemp(pattern);
        require(directory != nullptr, "PCM fixture directory");
        setenv("A10VM_STATE_ROOT", directory, 1);
        hw_device_t* device = nullptr;
        require(HAL_MODULE_INFO_SYM.common.methods->open(&HAL_MODULE_INFO_SYM.common,
            AUDIO_HARDWARE_INTERFACE, &device) == 0, "open production audio device");
        auto* audio = reinterpret_cast<audio_hw_device*>(device);
        const audio_format_t formats[] = {AUDIO_FORMAT_PCM_24_BIT_PACKED, AUDIO_FORMAT_PCM_8_24_BIT, AUDIO_FORMAT_PCM_32_BIT};
        for (auto format : formats) {
            audio_config config{};
            config.sample_rate = 48000; config.channel_mask = AUDIO_CHANNEL_OUT_STEREO; config.format = format;
            audio_stream_out* output = nullptr;
            require(audio->open_output_stream(audio, 1, AUDIO_DEVICE_OUT_SPEAKER,
                static_cast<audio_output_flags_t>(AUDIO_OUTPUT_FLAG_PRIMARY | AUDIO_OUTPUT_FLAG_FAST),
                &config, &output, "") == 0, "MIUI primary PCM24/32 output rejected");
            audio->close_output_stream(audio, output);
            config.sample_rate = 44100; config.channel_mask = AUDIO_CHANNEL_IN_MONO;
            require(audio->get_input_buffer_size(audio, &config) > 0, "MIUI PCM24/32 input buffer rejected");
        }
        sockaddr_un address{}; address.sun_family = AF_UNIX;
        std::snprintf(address.sun_path, sizeof(address.sun_path), "%s/audio.sock", directory);
        int listener = socket(AF_UNIX, SOCK_STREAM, 0);
        require(listener >= 0 && bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 &&
            listen(listener, 1) == 0, "PCM fixture socket");
        std::thread host(serve, listener);
        for (auto format : formats) {
            const int32_t samples24[] = {-8388608, -256, 0, 8388352};
            const int32_t samples32[] = {INT32_MIN, -65536, 0, 2147418112};
            size_t bytes = format == AUDIO_FORMAT_PCM_24_BIT_PACKED ? 12 : 16;
            std::vector<unsigned char> source(bytes), captured(bytes);
            for (size_t i = 0; i < 4; ++i) {
                int32_t sample = format == AUDIO_FORMAT_PCM_32_BIT ? samples32[i] : samples24[i];
                if (bytes == 12) {
                    for (int b = 0; b < 3; ++b) source[i * 3 + b] = static_cast<uint32_t>(sample) >> (8 * b);
                } else std::memcpy(source.data() + 4 * i, &sample, 4);
            }
            audio_config config{};
            config.sample_rate = 48000; config.channel_mask = AUDIO_CHANNEL_OUT_STEREO; config.format = format;
            audio_stream_out* output = nullptr;
            require(audio->open_output_stream(audio, 1, AUDIO_DEVICE_OUT_SPEAKER, AUDIO_OUTPUT_FLAG_PRIMARY,
                &config, &output, "") == 0, "open production PCM output");
            require(output->write(output, source.data(), bytes) == static_cast<ssize_t>(bytes), "guest PCM output byte count");
            audio->close_output_stream(audio, output);
            config.sample_rate = 44100; config.channel_mask = AUDIO_CHANNEL_IN_MONO;
            audio_stream_in* input = nullptr;
            require(audio->open_input_stream(audio, 2, AUDIO_DEVICE_IN_BUILTIN_MIC, &config, &input,
                AUDIO_INPUT_FLAG_NONE, "", AUDIO_SOURCE_MIC) == 0, "open production PCM input");
            require(input->read(input, captured.data(), bytes) == static_cast<ssize_t>(bytes), "guest PCM input byte count");
            require(captured == source, "24/32-bit capture sample conversion");
            audio->close_input_stream(audio, input);
        }
        host.join(); close(listener); unlink(address.sun_path); rmdir(directory);
        device->close(device);
        std::puts("miui_primary_pcm_formats=3\nhost_pcm_conversion=passed\ncapture_pcm_conversion=passed");
    } catch (const std::exception& error) {
        std::fprintf(stderr, "audio_pcm_regression: %s\n", error.what());
        return 1;
    }
}
