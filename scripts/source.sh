#!/usr/bin/env bash
# Fetch the kernel source tree.

set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WORKSPACE=${WORKSPACE:?WORKSPACE must be set}
KERNEL_DIR="${WORKSPACE}/android-kernel"

group "Cloning kernel source"
info "${KERNEL_SOURCE} @ ${KERNEL_SOURCE_BRANCH}"

ref_exists "$KERNEL_SOURCE" "$KERNEL_SOURCE_BRANCH" \
    || die "branch/tag '${KERNEL_SOURCE_BRANCH}' does not exist in ${KERNEL_SOURCE}"

rm -rf "$KERNEL_DIR"
retry 3 git clone -q --recursive --depth=1 \
    -b "$KERNEL_SOURCE_BRANCH" "$KERNEL_SOURCE" "$KERNEL_DIR" \
    || die "failed to clone ${KERNEL_SOURCE}"

# Clean malformed cmdline.c separators present in the configured kernel source.
CMDLINE_FILE="${KERNEL_DIR}/fs/proc/cmdline.c"
python3 - "$CMDLINE_FILE" <<'CLEAN_CMDLINE'
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
if not p.is_file():
    raise SystemExit(f"ERROR: missing {p}")

s = p.read_text()
s = re.sub(r'(?m)^[ \t]*#{10,}[ \t]*\r?$', '', s)
s = re.sub(
    r'(?m)^[ \t]*#static int cmdline_proc_show[^\n]*\n'
    r'(?:[ \t]*#(?:[^\n]*)\n){4}',
    '',
    s,
)
s = re.sub(r'\n{3,}', '\n\n', s)

if re.search(r'(?m)^[ \t]*#{10,}[ \t]*$', s):
    raise SystemExit("ERROR: hash separator remains in cmdline.c")
if re.search(r'(?m)^[ \t]*#static int cmdline_proc_show', s):
    raise SystemExit("ERROR: commented duplicate function remains")
if len(re.findall(r'(?m)^static int cmdline_proc_show\b', s)) != 1:
    raise SystemExit("ERROR: expected exactly one active cmdline_proc_show")
if "proc_command_line_init();" not in s:
    raise SystemExit("ERROR: proc_command_line_init() missing")
if 'proc_create("cmdline"' not in s:
    raise SystemExit('ERROR: proc_create("cmdline"...) missing')

p.write_text(s)
print("PASS: cmdline.c cleaned and validated")
CLEAN_CMDLINE


# KernelSU forks compute their version from the commit count, and several
# read it straight out of the enclosing git repo. A depth-1 clone reports 1
# commit, which produces a nonsense version. Unshallow just enough to count.
if [ -f "${KERNEL_DIR}/.git/shallow" ]; then
    debug "kernel tree is shallow; that is fine for building"
fi

KVER=$(kernel_version "$KERNEL_DIR") \
    || die "could not read VERSION/PATCHLEVEL from ${KERNEL_DIR}/Makefile -- is this a kernel tree?"
export_env KERNEL_VERSION "$KVER"
export_env KERNEL_DIR "$KERNEL_DIR"
ok "kernel source ready (Linux ${KVER})"
summary "| Kernel | \`${KERNEL_SOURCE##*/}\` @ \`${KERNEL_SOURCE_BRANCH}\` (Linux ${KVER}) |"

# LOCALVERSION is used purely to decorate artifact names.
if is_true "${ADD_LOCALVERSION_TO_FILENAME:-false}" && [ -f "${KERNEL_DIR}/localversion" ]; then
    export_env LOCALVERSION "$(cat "${KERNEL_DIR}/localversion")"
else
    export_env LOCALVERSION ""
fi
endgroup
