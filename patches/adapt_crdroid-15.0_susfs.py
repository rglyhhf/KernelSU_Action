
#!/usr/bin/env python3
"""Adapt susfs4ksu's 4.9 patch to the crDroid 15 statx-based VFS.

Usage:
    python3 adapt_crdroid_susfs.py PATCH_FILE KERNEL_SOURCE_DIR

The input patch is rewritten in place. Only its fs/stat.c and
fs/proc/cmdline.c sections are regenerated; all other SUSFS hunks are kept.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"[ERROR] {message}")


def replace_exactly_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one source anchor, found {count}")
    return source.replace(old, new, 1)


def make_file_diff(relative_path: str, original: str, modified: str) -> str:
    if original == modified:
        return ""

    hunks = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )

    if not hunks:
        return ""

    return f"diff --git a/{relative_path} b/{relative_path}\n{hunks}"


def adapt_stat_c(original: str, patch_text: str) -> str:
    # The original SUSFS namei.c patch must export filename_lookup(),
    # and fs/internal.h must declare it.
    if not re.search(r"(?m)^\+\s*extern int filename_lookup\(", patch_text):
        fail("the source patch does not declare filename_lookup() in fs/internal.h")

    if not re.search(r"(?m)^\+\s*int filename_lookup\(", patch_text):
        fail("the source patch does not export filename_lookup() from fs/namei.c")

    include_anchor = "#include <asm/unistd.h>\n"

    include_addition = (
        "\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "#include <linux/jump_label.h>\n"
        "#include <linux/susfs_def.h>\n"
        "#endif\n"
        "#include \"internal.h\"\n"
        "\n"
        "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
        "extern bool susfs_is_inode_sus_kstat(struct inode *inode, bool *out_is_fuse);\n"
        "extern void susfs_sus_kstat_spoof_generic_fillattr(struct inode *inode,\n"
        "\t\tstruct kstat *stat, u32 result_mask);\n"
        "#endif\n"
        "\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "extern struct static_key_true ksu_is_init_rc_hook_enabled;\n"
        "extern void ksu_handle_vfs_fstat(int fd, loff_t *kstat_size_ptr);\n"
        "extern struct static_key_true ksu_su_compat_enabled;\n"
        "extern bool __ksu_is_allow_uid_for_current(uid_t uid);\n"
        "extern int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);\n"
        "#endif\n"
    )

    if '#include "internal.h"' not in original:
        original = replace_exactly_once(
            original,
            include_anchor,
            include_anchor + include_addition,
            "fs/stat.c internal/SUSFS includes",
        )
    else:
        required = (
            "#include <linux/jump_label.h>",
            "#include <linux/susfs_def.h>",
            "extern bool susfs_is_inode_sus_kstat(",
            "extern void susfs_sus_kstat_spoof_generic_fillattr(",
            "extern struct static_key_true ksu_is_init_rc_hook_enabled;",
            "extern void ksu_handle_vfs_fstat(",
            "extern struct static_key_true ksu_su_compat_enabled;",
            "extern bool __ksu_is_allow_uid_for_current(",
            "extern int ksu_handle_stat(",
        )

        missing = [item for item in required if item not in original]

        if missing:
            fail(
                "fs/stat.c already has a partial SUSFS include block; missing: "
                + ", ".join(missing)
            )

    # KSTAT local variables.
    inode_anchor = "\tstruct inode *inode = d_backing_inode(path->dentry);\n"

    inode_addition = (
        "\tstruct inode *inode = d_backing_inode(path->dentry);\n"
        "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
        "\tu32 susfs_result_mask = 0;\n"
        "\tint susfs_error;\n"
        "#endif\n"
    )

    if "u32 susfs_result_mask = 0;" not in original:
        original = replace_exactly_once(
            original,
            inode_anchor,
            inode_addition,
            "vfs_getattr_nosec inode declaration",
        )

    # Cover both filesystem getattr and generic_fillattr.
    getattr_pattern = re.compile(
        r"\tif \(inode->i_op->getattr\)\n"
        r"\t\treturn inode->i_op->getattr\(path, stat, request_mask,\n"
        r"[\t ]+query_flags\);\n\n"
        r"\tgeneric_fillattr\(inode, stat\);\n"
        r"\treturn 0;"
    )

    getattr_replacement = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
        "\tif (susfs_is_current_app_uid()) {\n"
        "\t\tbool is_fuse = false;\n"
        "\t\tif (susfs_is_inode_sus_kstat(inode, &is_fuse))\n"
        "\t\t\tsusfs_result_mask = is_fuse ? STATX_SUS_KSTAT_FUSE : STATX_SUS_KSTAT;\n"
        "\t}\n"
        "\n"
        "\tif (inode->i_op->getattr) {\n"
        "\t\tsusfs_error = inode->i_op->getattr(path, stat, request_mask, query_flags);\n"
        "\t\tif (!susfs_error && susfs_result_mask)\n"
        "\t\t\tsusfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);\n"
        "\t\treturn susfs_error;\n"
        "\t}\n"
        "\n"
        "\tgeneric_fillattr(inode, stat);\n"
        "\tif (susfs_result_mask)\n"
        "\t\tsusfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);\n"
        "\treturn 0;\n"
        "#else\n"
        "\tif (inode->i_op->getattr)\n"
        "\t\treturn inode->i_op->getattr(path, stat, request_mask,\n"
        "\t\t\t\t\t\t    query_flags);\n"
        "\n"
        "\tgeneric_fillattr(inode, stat);\n"
        "\treturn 0;\n"
        "#endif"
    )

    if "susfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);" not in original:
        original, count = getattr_pattern.subn(
            getattr_replacement, original, count=1
        )

        if count != 1:
            fail(
                "vfs_getattr_nosec getattr/generic_fillattr body: "
                "expected exactly one source anchor"
            )

    # fstat compatibility in vfs_statx_fd().
    # Only change stat->size after vfs_getattr() succeeds.
    fd_pattern = re.compile(
        r"\t\terror = vfs_getattr\(&f.file->f_path, stat,\n"
        r"[\t ]+request_mask, query_flags\);\n"
        r"\t\tfdput\(f\);"
    )

    fd_replacement = (
        "\t\terror = vfs_getattr(&f.file->f_path, stat,\n"
        "\t\t\t\t    request_mask, query_flags);\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\t\tif (!error && static_branch_unlikely(&ksu_is_init_rc_hook_enabled))\n"
        "\t\t\tksu_handle_vfs_fstat(fd, &stat->size);\n"
        "#endif\n"
        "\t\tfdput(f);"
    )

    if "ksu_handle_vfs_fstat(fd, &stat->size);" not in original:
        original, count = fd_pattern.subn(
            fd_replacement, original, count=1
        )

        if count != 1:
            fail("vfs_statx_fd fstat hook: expected exactly one source anchor")

    # Path rewriting must occur before name lookup.
    # Scope this declaration anchor to vfs_statx(), because
    # readlinkat() also declares "struct path path;".
    path_decl_anchor = (
        "int vfs_statx(int dfd, const char __user *filename, int flags,\n"
        "\t      struct kstat *stat, u32 request_mask)\n"
        "{\n"
        "\tstruct path path;\n"
    )

    path_decl_replacement = path_decl_anchor + (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\tstruct filename *fname;\n"
        "#endif\n"
    )

    if "struct filename *fname;" not in original:
        original = replace_exactly_once(
            original,
            path_decl_anchor,
            path_decl_replacement,
            "vfs_statx local declarations",
        )

    lookup_anchor = (
        "retry:\n"
        "\terror = user_path_at(dfd, filename, lookup_flags, &path);"
    )

    lookup_replacement = (
        "retry:\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\tfname = getname_flags(filename, lookup_flags, NULL);\n"
        "\n"
        "\tif (likely(susfs_is_current_proc_no_su()))\n"
        "\t\tgoto orig_flow;\n"
        "\n"
        "\tif (static_branch_unlikely(&ksu_su_compat_enabled)) {\n"
        "\t\tif (unlikely(__ksu_is_allow_uid_for_current(current_uid().val)))\n"
        "\t\t\tksu_handle_stat(&dfd, &fname, &flags);\n"
        "\t}\n"
        "\n"
        "orig_flow:\n"
        "\terror = filename_lookup(dfd, fname, lookup_flags, &path, NULL);\n"
        "\t/* filename_lookup() releases fname on all non-ERR_PTR paths. */\n"
        "#else\n"
        "\terror = user_path_at(dfd, filename, lookup_flags, &path);\n"
        "#endif"
    )

    if "ksu_handle_stat(&dfd, &fname, &flags);" not in original:
        original = replace_exactly_once(
            original,
            lookup_anchor,
            lookup_replacement,
            "vfs_statx pathname lookup hook",
        )

    # Verify generated hooks.
    required = (
        "int vfs_statx_fd(unsigned int fd",
        "int vfs_statx(int dfd, const char __user *filename",
        "ksu_handle_vfs_fstat(fd, &stat->size);",
        "ksu_handle_stat(&dfd, &fname, &flags);",
        "susfs_sus_kstat_spoof_generic_fillattr(inode, stat, susfs_result_mask);",
    )

    for item in required:
        if item not in original:
            fail(f"generated fs/stat.c is missing required code: {item}")

    return original


def adapt_cmdline_c(original: str) -> str:
    # Do not duplicate an existing hook. Reject partial implementations.
    key = "susfs_is_fake_cmdline_or_bootconfig_buffer_set"
    helper = "susfs_spoof_cmdline_or_bootconfig"

    has_key = key in original
    has_helper = helper in original

    if has_key != has_helper:
        fail("fs/proc/cmdline.c contains a partial SUSFS cmdline hook")

    if has_key and has_helper:
        return original

    seq_include = "#include <linux/seq_file.h>\n"
    jump_include = "#include <linux/jump_label.h>\n"

    if jump_include not in original:
        original = replace_exactly_once(
            original,
            seq_include,
            seq_include + jump_include,
            "fs/proc/cmdline.c jump-label include",
        )

    declaration_anchor = "static char proc_command_line[COMMAND_LINE_SIZE];"

    declaration_block = (
        "#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG\n"
        "extern struct static_key_false susfs_is_fake_cmdline_or_bootconfig_buffer_set;\n"
        "extern void susfs_spoof_cmdline_or_bootconfig(struct seq_file *m);\n"
        "#endif\n\n"
        "static char proc_command_line[COMMAND_LINE_SIZE];"
    )

    original = replace_exactly_once(
        original,
        declaration_anchor,
        declaration_block,
        "fs/proc/cmdline.c SUSFS declarations",
    )

    function_anchor = (
        "static int cmdline_proc_show(struct seq_file *m, void *v)\n"
        "{\n"
    )

    function_replacement = (
        "static int cmdline_proc_show(struct seq_file *m, void *v)\n"
        "{\n"
        "#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG\n"
        "\tif (static_branch_likely(&susfs_is_fake_cmdline_or_bootconfig_buffer_set)) {\n"
        "\t\tsusfs_spoof_cmdline_or_bootconfig(m);\n"
        "\t\treturn 0;\n"
        "\t}\n"
        "#endif\n"
    )

    original = replace_exactly_once(
        original,
        function_anchor,
        function_replacement,
        "fs/proc/cmdline.c cmdline_proc_show hook",
    )

    return original


def split_diff_sections(patch_text: str):
    # Keep the original patch preamble and all unrelated diff sections.
    starts = [
        m.start()
        for m in re.finditer(r"(?m)^diff --git ", patch_text)
    ]

    if not starts:
        fail("input patch contains no 'diff --git' sections")

    preamble = patch_text[:starts[0]]
    sections = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(patch_text)
        section = patch_text[start:end]
        first_line = section.splitlines()[0]

        match = re.match(r"diff --git a/(.+) b/(.+)$", first_line)

        if not match or match.group(1) != match.group(2):
            fail(f"cannot parse diff section header: {first_line}")

        sections.append((match.group(1), section))

    return preamble, sections


def main() -> None:
    if len(sys.argv) != 3:
        fail("Usage: adapt_crdroid_susfs.py PATCH_FILE KERNEL_SOURCE_DIR")

    patch_file = Path(sys.argv[1]).resolve()
    kernel_dir = Path(sys.argv[2]).resolve()

    if not patch_file.is_file():
        fail(f"patch file not found: {patch_file}")

    if not kernel_dir.is_dir():
        fail(f"kernel source directory not found: {kernel_dir}")

    stat_path = kernel_dir / "fs/stat.c"
    cmdline_path = kernel_dir / "fs/proc/cmdline.c"

    for path in (stat_path, cmdline_path):
        if not path.is_file():
            fail(f"required target source file not found: {path}")

    patch_text = patch_file.read_text(encoding="utf-8")
    stat_original = stat_path.read_text(encoding="utf-8")
    cmdline_original = cmdline_path.read_text(encoding="utf-8")

    stat_modified = adapt_stat_c(stat_original, patch_text)
    cmdline_modified = adapt_cmdline_c(cmdline_original)

    stat_diff = make_file_diff(
        "fs/stat.c", stat_original, stat_modified
    )

    cmdline_diff = make_file_diff(
        "fs/proc/cmdline.c", cmdline_original, cmdline_modified
    )

    preamble, sections = split_diff_sections(patch_text)

    stat_count = sum(path == "fs/stat.c" for path, _ in sections)
    cmdline_count = sum(
        path == "fs/proc/cmdline.c" for path, _ in sections
    )

    if stat_count != 1:
        fail(f"expected exactly one fs/stat.c patch section, found {stat_count}")

    if cmdline_count > 1:
        fail(
            "expected at most one fs/proc/cmdline.c section, "
            f"found {cmdline_count}"
        )

    output_sections = []

    for path, section in sections:
        if path == "fs/stat.c":
            if stat_diff:
                output_sections.append(stat_diff)

        elif path == "fs/proc/cmdline.c":
            if cmdline_diff:
                output_sections.append(cmdline_diff)

        else:
            output_sections.append(section)

    if cmdline_count == 0 and cmdline_diff:
        output_sections.append(cmdline_diff)

    rewritten = preamble + "".join(output_sections)

    if not rewritten.endswith("\n"):
        rewritten += "\n"

    # Atomic replacement.
    temporary = patch_file.with_name(patch_file.name + ".tmp")

    temporary.write_text(
        rewritten,
        encoding="utf-8",
        newline="\n",
    )

    temporary.replace(patch_file)

    print("[+] Regenerated fs/stat.c for the target statx API.")
    print("[+] Preserved KSTAT, vfs_statx_fd fstat, and vfs_statx pathname hooks.")

    if cmdline_diff:
        print("[+] Regenerated fs/proc/cmdline.c SUSFS spoof hook from target source.")
    else:
        print("[+] Target fs/proc/cmdline.c already contains the SUSFS hook; no duplicate added.")

    print("[+] All unrelated SUSFS patch sections were preserved.")
    print(f"[+] Updated patch: {patch_file}")


if __name__ == "__main__":
    main()
