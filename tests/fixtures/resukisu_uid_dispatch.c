/* UID-filter cases from ReSukiSU 63ad1ea3/kernel/supercall/dispatch.c.
 * Keep a standard path command to verify it survives the compatibility patch.
 */
int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)
{
    switch (cmd) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    case CMD_SUSFS_ADD_SUS_PATH: {
        susfs_add_sus_path(arg);
        return 0;
    }
    case CMD_SUSFS_SET_SUS_PATH_UID_FILTER: {
        susfs_set_sus_path_uid_filter(arg);
        return 0;
    }
#endif //#ifdef CONFIG_KSU_SUSFS_SUS_PATH
#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER
    case CMD_SUSFS_SET_PRIORITY_UID_FILTER: {
        susfs_set_priority_uid_filter(arg);
        return 0;
    }
#endif // CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER
    }
    return 0;
}
