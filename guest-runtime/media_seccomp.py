"""Stage ARM64 media filters with the private Unix Binder transport allowed."""
from prepare import ROOT


def policies():
    upstream = ROOT / "artifacts/container/media/upstream/frameworks/av/services"
    output = ROOT / "artifacts/container/media/policies"
    output.mkdir(parents=True, exist_ok=True)
    transport = (ROOT / "guest-runtime/native/media-transport.policy").read_text(encoding="utf-8")
    sources = {
        "/system/apex/com.android.media/etc/seccomp_policy/mediaextractor.policy":
            upstream / "mediaextractor/seccomp_policy/mediaextractor-arm64.policy",
        "/system/apex/com.android.media.swcodec/etc/seccomp_policy/mediaswcodec.policy":
            upstream / "mediacodec/seccomp_policy/mediaswcodec-arm64.policy",
        "/system/etc/seccomp_policy/mediacodec.policy":
            upstream / "mediacodec/seccomp_policy/mediaswcodec-arm64.policy",
    }
    result = {}
    for guest, source in sources.items():
        target = output / guest.rsplit("/", 1)[1]
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        result[guest] = target
    for name in ("mediaextractor", "mediaswcodec", "mediacodec"):
        target = output / (name + "-transport.policy")
        target.write_text(transport, encoding="utf-8")
        result["/vendor/etc/seccomp_policy/" + name + ".policy"] = target
    return result
