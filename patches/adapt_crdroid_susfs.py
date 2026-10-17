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


# Adapt the final fdinfo.c hunk to crDroid's original fallback code.
start = text.find(
    "@@ -83,13 +101,44 @@ static void inotify_fdinfo"
)
end = text.find("diff --git a/fs/overlayfs/inode.c", start)

if start < 0 or end < 0:
    raise SystemExit("Cannot find the expected fdinfo.c patch section.")

fdinfo_lines = [
    " \tinode_mark = container_of(mark, struct inotify_inode_mark, fsn_mark);",
    " \tinode = igrab(mark->inode);",
    " \tif (inode) {",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT",
    "+\t\tu32 mask = mark->mask & IN_ALL_EVENTS;",
    "+\t\tif (likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC) &&",
    "+\t\t\t\tunlikely(inode->i_state & INODE_STATE_SUS_KSTAT)) {",
    "+\t\t\tstruct path path;",
    "+\t\t\tchar *pathname = kmalloc(PAGE_SIZE, GFP_KERNEL);",
    "+\t\t\tchar *dpath;",
    "+\t\t\tif (!pathname) {",
    "+\t\t\t\tgoto out_seq_printf;",
    "+\t\t\t}",
    "+\t\t\tdpath = d_path(&file->f_path, pathname, PAGE_SIZE);",
    "+\t\t\tif (!dpath) {",
    "+\t\t\t\tgoto out_free_pathname;",
    "+\t\t\t}",
    "+\t\t\tif (kern_path(dpath, 0, &path)) {",
    "+\t\t\t\tgoto out_free_pathname;",
    "+\t\t\t}",
    "+\t\t\tseq_printf(m, \"inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:%x \",",
    "+\t\t\t\t   inode_mark->wd, path.dentry->d_inode->i_ino,",
    "+\t\t\t\t   path.dentry->d_inode->i_sb->s_dev,",
    "+\t\t\t\t   mask, mark->ignored_mask);",
    "+\t\t\tshow_mark_fhandle(m, path.dentry->d_inode);",
    "+\t\t\tseq_putc(m, '\\n');",
    "+\t\t\tiput(inode);",
    "+\t\t\tpath_put(&path);",
    "+\t\t\tkfree(pathname);",
    "+\t\t\treturn;",
    "+out_free_pathname:",
    "+\t\t\tkfree(pathname);",
    "+\t\t}",
    "+out_seq_printf:",
    "+#endif",
    " \t\tseq_printf(m, \"inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:0 \",",
    " \t\t\t   inode_mark->wd, inode->i_ino, inode->i_sb->s_dev,",
    " \t\t\t   inotify_mark_user_mask(mark));",
    " \t\tshow_mark_fhandle(m, inode);",
    " \t\tseq_putc(m, '\\n');",
    " \t\tiput(inode);",
    " \t}",
]

fdinfo_hunk = make_hunk(
    83,
    101,
    "static void inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)",
    fdinfo_lines,
)
text = text[:start] + fdinfo_hunk + text[end:]


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
    "@@ -17,2 +20,8 @@",
    " #include <asm/unistd.h>",
    "+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT",
    "+extern bool susfs_is_inode_sus_kstat(struct inode *inode, bool *out_is_fuse);",
    "+extern void susfs_sus_kstat_spoof_generic_fillattr(struct inode *inode, struct kstat *stat, u32 result_mask);",
    "+#endif",
    " ",
    "@@ -68,6 +74,20 @@",
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
patch_file.write_text(text, encoding="utf-8")

print("[+] Generated crDroid-compatible SUSFS patch hunks.")
