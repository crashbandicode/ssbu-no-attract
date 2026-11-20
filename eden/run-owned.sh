#!/bin/sh
# Execute this on the admitted host via a bounded transient service.
set -eu
run=$1
cap=$2
host=${3:-xps}
recovery_s=${4:-0}
playbook=/tmp/no-attract-playbook
check_ledger() {
    if [ "$host" = yoga ]; then
        /usr/bin/cat /tmp/deluxe-surface-1007/OWNER-COORDINATION.md > "$run/admission-ledger.md"
    else
        /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=5 memento-claw-yoga-ubuntu '/usr/bin/cat /tmp/deluxe-surface-1007/OWNER-COORDINATION.md' > "$run/admission-ledger.md"
    fi
    /usr/bin/python3 -B "$run/rows/admission.py" "$host" < "$run/admission-ledger.md"
}
check_processes() {
    if /usr/bin/pgrep -a -x 'Eden.AppImage|eden|eden-real|rustc|cargo|clang|clang-18|clang-19|clang-20'; then
        return 1
    fi
    /usr/bin/free -b
    /usr/bin/df -B1 "$run"
}
cleanup() {
    code=$?
    trap - EXIT
    if [ -f "$run/state/lifecycle.json" ]; then
        /usr/bin/timeout 240s /usr/bin/python3 -B -I "$playbook/tools/eden-test/eden_test.py" down "$run" > "$run/supervisor-down.log" 2>&1 || exit 90
    fi
    printf '%s\n' "$code" > "$run/supervisor-result.txt"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM INT
{
    date -u -Is
    check_ledger
    check_processes
} > "$run/pre-up-admission.log" 2>&1
/usr/bin/timeout 240s /usr/bin/python3 -B -I "$playbook/tools/eden-test/eden_test.py" up "$run" > "$run/supervisor-up.log" 2>&1
if /usr/bin/timeout "${cap}s" /usr/bin/python3 -B -I "$playbook/tools/eden-test/eden_test.py" run "$run" > "$run/supervisor-run.log" 2>&1; then
    exit 0
else
    failed=$?
fi
if [ "$recovery_s" -gt 0 ] && [ -f "$run/out/main-idle-2x/candidate-main-idle.json" ]; then
    # Each continuation requires a separately diagnosed and owner-issued
    # signal. Keep one hard deadline across all continuations.
    date -u -Is > "$run/recovery-window-opened.txt"
    expires=$(( $(date +%s) + recovery_s ))
    attempt=0
    while [ "$attempt" -lt 3 ]; do
        remaining=$(( expires - $(date +%s) ))
        [ "$remaining" -gt 0 ] || break
        if [ ! -f "$run/resume-native-route" ]; then
            sleep 2
            continue
        fi
        attempt=$((attempt + 1))
        mv "$run/resume-native-route" "$run/resume-native-route.$attempt"
        if /usr/bin/timeout "${remaining}s" /usr/bin/python3 -B -I "$playbook/tools/eden-test/eden_test.py" run "$run" --retry > "$run/supervisor-retry-$attempt.log" 2>&1; then
            exit 0
        else
            failed=$?
            printf '%s\n' "$failed" > "$run/supervisor-retry-$attempt.result"
        fi
    done
fi
exit "$failed"
