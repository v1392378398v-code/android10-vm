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

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
void transfer(int fd, void* data, size_t bytes, bool output) {
    auto* cursor = static_cast<char*>(data);
    while (bytes) {
        const ssize_t result = output ? send(fd, cursor, bytes, MSG_NOSIGNAL) : recv(fd, cursor, bytes, 0);
        require(result > 0, "mock audio transport");
        cursor += result;
        bytes -= result;
    }
}
uint32_t readWord(int fd) {
    uint32_t word;
    transfer(fd, &word, sizeof(word), false);
    return ntohl(word);
}
void writeWord(int fd, uint32_t word) {
    word = htonl(word);
    transfer(fd, &word, sizeof(word), true);
}
void writeLong(int fd, uint64_t value) {
    writeWord(fd, value >> 32);
    writeWord(fd, value);
}
void serve(int listener) {
    for (int cycle = 0; cycle < 3; ++cycle) {
        const int fd = accept(listener, nullptr, nullptr);
        require(fd >= 0, "mock audio accept");
        require(readWord(fd) == 0x41313041 && readWord(fd) == 1, "mock audio header");
        require(readWord(fd) == 0 && readWord(fd) == 48000, "mock output sample rate");
        require(readWord(fd) == 2 && readWord(fd) == 2, "mock output PCM16 stereo");
        readWord(fd);
        writeWord(fd, 0);
        writeWord(fd, 8192);
        uint64_t written = 0;
        for (;;) {
            uint32_t command;
            if (recv(fd, &command, sizeof(command), MSG_WAITALL) == 0) break;
            command = ntohl(command);
            if (command == 1) {
                const uint32_t bytes = readWord(fd);
                std::vector<char> pcm(bytes);
                transfer(fd, pcm.data(), bytes, false);
                written += bytes / 4;
                writeWord(fd, bytes);
            } else {
                require(command == 3, "mock audio command");
                writeWord(fd, 0);
                writeLong(fd, written > 64 ? written - 64 : 0);
                writeLong(fd, 123456789000ULL + cycle);
            }
        }
        close(fd);
    }
}
}

int main() {
    std::setbuf(stdout, nullptr);
    const char* temporary = getenv("TMPDIR");
    std::string pattern = std::string(temporary ? temporary : ".") + "/audio-clock-XXXXXX";
    char* directory = mkdtemp(pattern.data());
    require(directory != nullptr, "mock audio directory");
    setenv("A10VM_STATE_ROOT", directory, 1);
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    require(std::snprintf(address.sun_path, sizeof(address.sun_path), "%s/audio.sock", directory) <
            static_cast<int>(sizeof(address.sun_path)), "mock audio path");
    const int listener = socket(AF_UNIX, SOCK_STREAM, 0);
    require(listener >= 0 && bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 &&
            listen(listener, 1) == 0, "mock audio listen");
    std::thread host(serve, listener);
    try {
        hw_device_t* device = nullptr;
        require(HAL_MODULE_INFO_SYM.common.methods->open(&HAL_MODULE_INFO_SYM.common,
                AUDIO_HARDWARE_INTERFACE, &device) == 0, "open production audio HAL");
        auto* audio = reinterpret_cast<audio_hw_device*>(device);
        audio_config config{};
        config.sample_rate = 48000;
        config.channel_mask = AUDIO_CHANNEL_OUT_STEREO;
        config.format = AUDIO_FORMAT_PCM_16_BIT;
        audio_stream_out* output = nullptr;
        require(audio->open_output_stream(audio, 1, AUDIO_DEVICE_OUT_SPEAKER, AUDIO_OUTPUT_FLAG_NONE,
                &config, &output, "") == 0, "open production output stream");
        std::vector<char> pcm(4096 * 4);
        uint64_t total = 0;
        for (int cycle = 0; cycle < 3; ++cycle) {
            uint64_t presented = 0;
            timespec time{};
            for (int write = 0; write < 4; ++write) {
                require(output->write(output, pcm.data(), pcm.size()) == static_cast<ssize_t>(pcm.size()),
                        "production HAL PCM write");
                total += pcm.size() / 4;
            }
            require(output->get_presentation_position(output, &presented, &time) == 0,
                    "production presentation timestamp");
            std::printf("audio_clock_cycle=%d written=%llu presented=%llu\n", cycle,
                    static_cast<unsigned long long>(total), static_cast<unsigned long long>(presented));
            require(presented == total - 64, "Presentation frame count reset across standby");
            uint32_t rendered = 0;
            require(output->get_render_position(output, &rendered) == 0 && rendered == 16384 - 64,
                    "Render frame count must restart after standby");
            require(time.tv_sec == 123 && time.tv_nsec == 456789000 + cycle,
                    "Host monotonic timestamp changed");
            require(output->common.standby(&output->common) == 0, "production standby");
        }
        audio->close_output_stream(audio, output);
        device->close(device);
        host.join();
        close(listener);
        unlink(address.sun_path);
        rmdir(directory);
        std::puts("audio_clock_standby_reconnect=1\naudio_clock_render_reset=1\naudio_clock_complete=1");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "audio_clock_error=%s\n", error.what());
        std::_Exit(1);
    }
}
