#!/usr/bin/env bash
# Regressions for older SUSFS APIs and downloaded-script stdout.
set -euo pipefail
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
export KERNEL_DIR="$TEST_ROOT/kernel"
mkdir -p "$KERNEL_DIR/KernelSU/kernel/supercall" "$KERNEL_DIR/include/linux" "$KERNEL_DIR/fs" "$KERNEL_DIR/drivers"
ln -s ../KernelSU/kernel "$KERNEL_DIR/drivers/kernelsu"
# shellcheck source=scripts/patches.sh
. "$REPO_ROOT/scripts/patches.sh"

# fetch_stdout must pipe only the downloaded body to the interpreter.
curl() { printf 'printf "installer-ok\\n"\n'; }
fetch_stdout mock | bash -e > "$TEST_ROOT/installer-output" 2> "$TEST_ROOT/installer-error"
[ "$(cat "$TEST_ROOT/installer-output")" = installer-ok ]

# A retried download must keep its body separate from progress messages too.
sleep() { :; }
flaky_download() {
    if [ ! -f "$TEST_ROOT/retried" ]; then
        touch "$TEST_ROOT/retried"
        return 1
    fi
    printf payload
}
retry 2 flaky_download > "$TEST_ROOT/download-body" 2> "$TEST_ROOT/download-log"
[ "$(cat "$TEST_ROOT/download-body")" = payload ]
grep -q NETWORK-RETRY "$TEST_ROOT/download-log"
grep -q 'attempt 1/2 failed' "$TEST_ROOT/download-log"

# Apply to a representative upstream dispatcher, then verify idempotence.
cp "$REPO_ROOT/tests/fixtures/resukisu_uid_dispatch.c" "$KERNEL_DIR/KernelSU/kernel/supercall/dispatch.c"
susfs_resukisu_compat "$KERNEL_DIR/KernelSU"
cp "$KERNEL_DIR/KernelSU/kernel/supercall/dispatch.c" "$TEST_ROOT/dispatch-once.c"
susfs_resukisu_compat "$KERNEL_DIR/KernelSU"
cmp "$TEST_ROOT/dispatch-once.c" "$KERNEL_DIR/KernelSU/kernel/supercall/dispatch.c"

# Test configuration against both incomplete and complete priority APIs.
cat > "$KERNEL_DIR/KernelSU/kernel/Kconfig" <<'KCONFIG'
config KSU_SUSFS
config KSU_SUSFS_SUS_PATH
config KSU_SUSFS_PRIORITY_UID_FILTER
KCONFIG
touch "$KERNEL_DIR/fs/Kconfig" "$KERNEL_DIR/include/linux/susfs_def.h" "$KERNEL_DIR/include/linux/susfs.h"
printf 'CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y\n' > "$TEST_ROOT/defconfig"
susfs_defconfig "$TEST_ROOT/defconfig"
grep -qx '# CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER is not set' "$TEST_ROOT/defconfig"
grep -qx 'CONFIG_KSU_SUSFS_SUS_PATH=y' "$TEST_ROOT/defconfig"
printf '#define CMD_SUSFS_SET_PRIORITY_UID_FILTER 3\n' > "$KERNEL_DIR/include/linux/susfs_def.h"
susfs_defconfig "$TEST_ROOT/defconfig"
grep -qx '# CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER is not set' "$TEST_ROOT/defconfig"
printf 'void susfs_set_priority_uid_filter(void **arg);\n' > "$KERNEL_DIR/include/linux/susfs.h"
susfs_defconfig "$TEST_ROOT/defconfig"
grep -qx 'CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y' "$TEST_ROOT/defconfig"

# Compile and execute with the two API generations. Deliberately keep the
# priority Kconfig enabled for the old API to prove its handler is guarded.
if command -v cc >/dev/null; then
    cat > "$TEST_ROOT/dispatch-test.c" <<'C'
#define __user
#define CONFIG_KSU_SUSFS_SUS_PATH
#define CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER
#define CMD_SUSFS_ADD_SUS_PATH 1
static int calls;
static void susfs_add_sus_path(void **arg) { (void)arg; calls += 1; }
#ifdef TEST_UID_FILTERS
#define CMD_SUSFS_SET_SUS_PATH_UID_FILTER 2
#define CMD_SUSFS_SET_PRIORITY_UID_FILTER 3
static void susfs_set_sus_path_uid_filter(void **arg) { (void)arg; calls += 10; }
static void susfs_set_priority_uid_filter(void **arg) { (void)arg; calls += 100; }
#endif
#include "dispatch.c"
int main(void)
{
    void *arg = 0;
    ksu_handle_susfs_cmd(1, &arg);
    if (calls != 1) return 1;
    ksu_handle_susfs_cmd(2, &arg);
    ksu_handle_susfs_cmd(3, &arg);
#ifdef TEST_UID_FILTERS
    return calls != 111;
#else
    return calls != 1;
#endif
}
C
    cp "$TEST_ROOT/dispatch-once.c" "$TEST_ROOT/dispatch.c"
    cc -std=c99 -Wall -Wextra -Werror "$TEST_ROOT/dispatch-test.c" -o "$TEST_ROOT/legacy"
    "$TEST_ROOT/legacy"
    cc -std=c99 -Wall -Wextra -Werror -DTEST_UID_FILTERS "$TEST_ROOT/dispatch-test.c" -o "$TEST_ROOT/modern"
    "$TEST_ROOT/modern"
else
    [ "${REQUIRE_CC:-false}" != true ] || die "C compiler required for compatibility regression tests"
    info "C compiler unavailable; dispatcher compilation will run in CI"
fi
ok "SUSFS compatibility and download stdout regressions passed"
