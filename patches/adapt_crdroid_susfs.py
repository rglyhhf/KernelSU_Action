#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: adapt_crdroid_susfs.py PATCH_FILE")

patch_file = Path(sys.argv[1])
text = patch_file.read_text(encoding="utf-8")


def make_hunk(old_start, new_start, heading, lines):
    old_count = sum(
        line.startswith((" ", "-")) for line in lines
    )
    new_count = sum(
        line.startswith((" ", "+")) for line in lines
    )
    header = (
        f"@@ -{old_start},{old_count} "
        f"+{new_start},{new_count} @@ {heading}"
    )
    return header + "\n" + "\n".join(lines) + "\n"


# Split stat.c changes into small hunks matching crDroid's source layout.
start = text.find("diff --git a/fs/stat.c b/fs/stat.c")
end = text.find("diff --git a/fs/statfs.c b/fs/statfs.c", start)

if start < 0 or end < 0:
    raise SystemExit("Cannot find the expected stat.c patch section.")

stat_section = "\n".join([
    "diff --git a/fs/stat.c b/fs/stat.c",
    "index 1591e16e9ce35..36021103fce4a 100644",
    "--- a/fs/stat.c",
    "+++ b/fs/stat.c",
    "@@ -15,2 +15,5 @@",
    " #include <linux/pagemap.h>",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+#include <linux/susfs_def.h>",
    "+#endif",
    " #include <asm/uaccess.h>",
    "@@ -17,2 +20,6 @@",
    " #include <asm/unistd.h>",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+extern bool susfs_is_inode_sus_kstat(struct inode *inode, bool *out_is_fuse);",
    "+extern void susfs_sus_kstat_spoof_generic_fillattr(struct inode *inode, struct kstat *stat, u32 result_mask);",
    "+#endif",
    " ",
    "@@ -68,16 +75,33 @@",
    " int vfs_getattr_nosec(const struct path *path, struct kstat *stat,",
    "                      u32 request_mask, unsigned int query_flags)",
    " {",
    "     struct inode *inode = d_backing_inode(path->dentry);",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+    u32 susfs_result_mask = 0;",
    "+    if (susfs_is_current_app_uid()) {",
    "+        bool is_fuse = false;",
    "+        if (susfs_is_inode_sus_kstat(inode, &is_fuse))",
    "+            susfs_result_mask = is_fuse ? STATX_SUS_KSTAT_FUSE : STATX_SUS_KSTAT;",
    "+    }",
    "+#endif",
    " ",
    "     memset(stat, 0, sizeof(*stat));",
    "     stat->result_mask |= STATX_BASIC_STATS;",
    "     request_mask &= STATX_ALL;",
    "     query_flags &= KSTAT_QUERY_FLAGS;",
    "-    if (inode->i_op->getattr)",
    "-        return inode->i_op->getattr(path, stat, request_mask,",
    "-                                    query_flags);",
    "+    if (inode->i_op->getattr) {",
    "+        int error = inode->i_op->getattr(path, stat, request_mask, query_flags);",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+        if (!error && susfs_result_mask)",
    "+            susfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);",
    "+#endif",
    "+        return error;",
    "+    }",
    " ",
    "     generic_fillattr(inode, stat);",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+    if (susfs_result_mask)",
    "+        susfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);",
    "+#endif",
    "     return 0;",
    " }",
]) + "\n"

text = text[:start] + stat_section + text[end:]

# The target kernel already implements SUSFS cmdline spoofing.
# Remove this patch section to prevent duplicate application.
patch_lines = text.splitlines(keepends=True)
cmdline_start = next(
    (i for i, line in enumerate(patch_lines)
     if line.startswith("diff --git a/fs/proc/cmdline.c ")),
    None,
)
if cmdline_start is not None:
    cmdline_end = next(
        (i for i in range(cmdline_start + 1, len(patch_lines))
         if patch_lines[i].startswith("diff --git ")),
        len(patch_lines),
    )
    del patch_lines[cmdline_start:cmdline_end]
    text = "".join(patch_lines)
    print("[+] Removed duplicate fs/proc/cmdline.c patch section.")

patch_file.write_text(text, encoding="utf-8")

print("[+] Generated crDroid-compatible SUSFS patch hunks.")
