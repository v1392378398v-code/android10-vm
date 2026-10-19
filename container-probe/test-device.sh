#!/bin/sh
# Installation transport may use a developer's root shell; the probe runs in its APK UID.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LOCAL_ROOT=0
GRAPHICS=0
SURFACE=0
PROPERTIES=0
BOOTSTRAP=0
DYNAMIC=0
COMPANION=0
BINDER=0
FILESYSTEM=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --local-root) LOCAL_ROOT=1; shift ;;
        --graphics) GRAPHICS=1; shift ;;
        --surface) SURFACE=1; GRAPHICS=1; shift ;;
        --properties) PROPERTIES=1; shift ;;
        --bootstrap) BOOTSTRAP=1; PROPERTIES=1; shift ;;
        --dynamic) DYNAMIC=1; BOOTSTRAP=1; PROPERTIES=1; shift ;;
        --companion) COMPANION=1; DYNAMIC=1; BOOTSTRAP=1; PROPERTIES=1; shift ;;
        --binder) BINDER=1; shift ;;
        --filesystem) FILESYSTEM=1; DYNAMIC=1; BOOTSTRAP=1; PROPERTIES=1; shift ;;
        *) break ;;
    esac
done
APK=${1:-"$ROOT/container-probe/build/outputs/apk/debug/container-probe-debug.apk"}
OUT="$ROOT/artifacts/container/g1-stage0"
EXTRAS=
INSTRUMENT_TIMEOUT=45
if [ "$GRAPHICS" = 1 ]; then
    OUT="$ROOT/artifacts/container/graphics/device"
    EXTRAS='-e graphics true'
fi
if [ "$SURFACE" = 1 ]; then
    OUT="$ROOT/artifacts/container/graphics/window/device"
    DURATION=${A10VM_WINDOW_MS:-60000}
    TOUCHES=${A10VM_WINDOW_TOUCHES:-100}
    case "$DURATION:$TOUCHES" in *[!0-9:]*) printf 'Window test parameters must be integers.\n' >&2; exit 2 ;; esac
    EXTRAS="$EXTRAS -e surface true -e windowDurationMs $DURATION -e windowTouches $TOUCHES"
    INSTRUMENT_TIMEOUT=150
fi
if [ "$PROPERTIES" = 1 ]; then
    OUT="$ROOT/artifacts/container/properties/device"
    EXTRAS="$EXTRAS -e properties true"
fi
if [ "$BOOTSTRAP" = 1 ]; then
    OUT="$ROOT/artifacts/container/runtime/device"
    EXTRAS="$EXTRAS -e bootstrap true"
fi
if [ "$DYNAMIC" = 1 ]; then
    OUT="$ROOT/artifacts/container/runtime/dynamic/device"
    EXTRAS="$EXTRAS -e dynamic true"
    INSTRUMENT_TIMEOUT=90
fi
if [ "$COMPANION" = 1 ]; then
    OUT="$ROOT/artifacts/container/runtime/companion/device"
    EXTRAS="$EXTRAS -e companion true"
    INSTRUMENT_TIMEOUT=120
fi
if [ "$BINDER" = 1 ]; then
    OUT="$ROOT/artifacts/container/runtime/binder/device"
    EXTRAS="$EXTRAS -e binder true"
    INSTRUMENT_TIMEOUT=150
fi
if [ "$FILESYSTEM" = 1 ]; then
    OUT="$ROOT/artifacts/container/runtime/filesystem/device"
    EXTRAS="$EXTRAS -e filesystem true"
    INSTRUMENT_TIMEOUT=120
fi
PACKAGE=io.a10vm.containerprobe
unset LD_LIBRARY_PATH LD_PRELOAD
for tool in jq timeout od tr sha256sum aapt2; do command -v "$tool" >/dev/null; done
test -f "$APK"
test "$(aapt2 dump badging "$APK" | sed -n "s/^package: name='\([^']*\)'.*/\1/p")" = "$PACKAGE"
if [ "$LOCAL_ROOT" = 1 ]; then
    command -v su >/dev/null
    test "$(timeout 10 su -c 'id -u')" = 0
else
    command -v adb >/dev/null
    test "$(adb get-state)" = device
fi
mkdir -p "$OUT"
device() {
    if [ "$LOCAL_ROOT" = 1 ]; then timeout "${2:-45}" su -c "$1";
    else timeout "${2:-45}" adb shell "$1"; fi
}
package_state() {
    log="$OUT/$1.log"
    if device "pm path $PACKAGE" > "$log" 2>&1; then
        if grep -q '^package:' "$log"; then return 0; fi
    else
        code=$?
        if [ "$code" = 1 ] && [ ! -s "$log" ]; then return 1; fi
    fi
    return 2
}
state=0
package_state preinstall-state || state=$?
if [ "$state" = 0 ]; then
    printf 'Existing probe installation found; export its report and uninstall it first.\n' >&2
    exit 2
elif [ "$state" != 1 ]; then
    printf 'Package state query failed; inspect %s/preinstall-state.log\n' "$OUT" >&2
    exit 1
fi
INSTALL_ATTEMPTED=0
cleanup() {
    result=$?
    trap - 0
    if [ "$INSTALL_ATTEMPTED" = 1 ]; then
        state=0
        package_state cleanup-state || state=$?
        case "$state" in
            0) if ! device "pm uninstall $PACKAGE" > "$OUT/uninstall.log" 2>&1; then
                   printf 'Probe cleanup failed; inspect %s/uninstall.log\n' "$OUT" >&2
                   result=1
               fi ;;
            1) printf 'Probe package absent.\n' > "$OUT/uninstall.log" ;;
            *) printf 'Probe cleanup state is unknown; inspect %s/cleanup-state.log\n' "$OUT" >&2
               result=1 ;;
        esac
    fi
    exit "$result"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
INSTALL_ATTEMPTED=1
if [ "$LOCAL_ROOT" = 1 ]; then
    device "pm install -r -S $(stat -c %s "$APK")" < "$APK" > "$OUT/install.log" 2>&1
else
    timeout 45 adb install -r "$APK" > "$OUT/install.log" 2>&1
fi
NONCE=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
device "am instrument -w -r -e nonce $NONCE $EXTRAS $PACKAGE/.ProbeInstrumentation" "$INSTRUMENT_TIMEOUT" \
    > "$OUT/instrumentation.log" 2>&1
if [ "$LOCAL_ROOT" = 1 ]; then
    device "cat /data/user/0/$PACKAGE/files/g1-stage0-report.json" > "$OUT/report.json"
else
    timeout 15 adb exec-out run-as "$PACKAGE" cat files/g1-stage0-report.json > "$OUT/report.json"
fi
sha256sum "$APK" > "$OUT/apk.sha256"
jq '{gate, passed, completeG1, hostSdk, targetSdk, appUid, pageSize,
     guestLibraryIsolationPassed, hostControlDetected, missingLibcRejected,
     validatorMissingContextRejected, validatorWrongContextRejected, error}' "$OUT/report.json"
if [ "$GRAPHICS" = 1 ]; then
    jq '.graphics | {gate, passed, guestLibraryIsolationPassed, surfaceVerified, desktopVerified, error}' "$OUT/report.json"
    jq -e '.graphics.passed' "$OUT/report.json" >/dev/null
fi
if [ "$SURFACE" = 1 ]; then
    jq '.window | {gate, passed, gpu, measurement:(.measurement | del(.samples)), cleanup, error}' "$OUT/report.json"
    jq -e '.window.passed' "$OUT/report.json" >/dev/null
fi
if [ "$PROPERTIES" = 1 ]; then
    jq '.properties | {gate, passed, guestLibraryIsolationPassed, hostControlDetected,
        appUid, hostSdk, checks: (.checks | length), instancesRemoved, runtimeIntegration,
        api: (.api | {passed, runtimeIntegration, cases: (.runs | length)})}' "$OUT/report.json"
    jq -e '.properties.passed' "$OUT/report.json" >/dev/null
fi
if [ "$BOOTSTRAP" = 1 ]; then
    jq '.properties.bootstrap | {gate, passed, staticBionicBootstrap, dynamicRuntimeIntegrated,
        cases: [.runs[] | {mode, passed, ownExecutableOnly, privateReadonlyMappingsPassed}]}' "$OUT/report.json"
    jq -e '.properties.bootstrap.passed' "$OUT/report.json" >/dev/null
fi
if [ "$DYNAMIC" = 1 ]; then
    jq '.properties.dynamic | {gate, passed, loaderFromSource, dynamicRuntimeIntegrated,
        concurrentAllocatorVerified,
        cases: [.runs[] | {mode, passed, guestLibraryIsolationPassed, privateReadonlyMappingsPassed}],
        rejected: [.rejected[] | {mode, passed}]}' "$OUT/report.json"
    jq -e '.properties.dynamic.passed' "$OUT/report.json" >/dev/null
fi
if [ "$COMPANION" = 1 ]; then
    jq '.properties.companion | {gate, passed, librariesFromSource, aarch64LlvmUnwindAdaptation,
        runs: [.runs[] | {passed, checks: (.checks | length), guestLibraryIsolationPassed,
            privateReadonlyMappingsPassed}], termination: [.termination[] | {mode, passed}],
        rejected: [.rejected[] | {missing, passed}]}' "$OUT/report.json"
    jq -e '.properties.companion.passed' "$OUT/report.json" >/dev/null
fi
if [ "$BINDER" = 1 ]; then
    jq '.binder | {gate, passed, completeG2, appUid, ordinaryAppUid,
        requiredClientCheckCount, clientChecks: (.clientChecks | length), lifecycleChecks,
        resourcesReclaimed, finalStats, brokerDisconnectNormalExit, processes, error}' "$OUT/report.json"
    jq -e '.binder.passed and (.binder.appUid >= 10000)' "$OUT/report.json" >/dev/null
    jq '.hwbinder | {gate, passed, completeG2, appUid, ordinaryAppUid,
        requiredClientCheckCount, clientChecks: (.clientChecks | length), lifecycleChecks,
        resourcesReclaimed, finalStats, brokerDisconnectNormalExit, processes, error}' "$OUT/report.json"
    jq -e '.hwbinder.passed and (.hwbinder.appUid >= 10000)' "$OUT/report.json" >/dev/null
fi
if [ "$FILESYSTEM" = 1 ]; then
    jq '.properties.filesystem | {gate, passed, rootRequired, completeG1, desktopVerified,
        checks: (.checks | length), identity, validatorNegativeCases}' "$OUT/report.json"
    jq -e '.properties.filesystem.passed and .properties.filesystem.identity.passed' "$OUT/report.json" >/dev/null
fi
jq -e --arg nonce "$NONCE" '.passed and (.nonce == $nonce)' "$OUT/report.json" >/dev/null
