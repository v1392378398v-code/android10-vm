#!/system/bin/sh
# Test observer: retain pressure samples and stop only the tested package at the floor.
set -eu
duration=${1:-360}
floor=${2:-327680}
app_uid=$(run-as io.a10vm.miui /system/bin/id -u)
printf 'observer_pid=%s\napp_uid=%s\nminimum_available_kb=%s\n' "$$" "$app_uid" "$floor"
sample=0
low=0
while [ "$sample" -lt "$duration" ]; do
    available=0
    swap_free=0
    while read -r key value unit; do
        case "$key" in
            MemAvailable:) available=$value ;;
            SwapFree:) swap_free=$value ;;
        esac
    done < /proc/meminfo
    processes=$(ps -A -o UID,RSS | {
        count=0
        total=0
        while read -r uid rss; do
            if [ "$uid" = "$app_uid" ]; then
                count=$((count + 1))
                total=$((total + rss))
            fi
        done
        printf 'app_processes=%s app_rss_sum_kb=%s' "$count" "$total"
    })
    printf 'sample=%s available_kb=%s swap_free_kb=%s %s\n' "$sample" "$available" "$swap_free" "$processes"
    if [ "$available" -lt 786432 ] && [ "$((sample % 5))" -eq 0 ]; then
        ps -A -o UID,PID,RSS,NAME | while read -r uid pid rss name; do
            if [ "$uid" = "$app_uid" ] && [ -r "/proc/$pid/oom_score_adj" ]; then
                if read -r adjustment < "/proc/$pid/oom_score_adj"; then
                    printf 'process sample=%s pid=%s rss_kb=%s adj=%s name=%s\n' "$sample" "$pid" "$rss" "$adjustment" "$name"
                fi
            fi
        done
    fi
    if [ "$available" -lt "$floor" ]; then low=$((low + 1)); else low=0; fi
    if [ "$low" -ge 2 ]; then
        printf 'test_aborted=host_memory_floor\n'
        am force-stop io.a10vm.miui
        exit 20
    fi
    sample=$((sample + 1))
    sleep 1
done
printf 'memory_observation=complete\n'
