/* Optional refresh calls from ReSukiSU 63ad1ea3/manager/throne_tracker.c. */
#include "ksu.h"
void compat_refresh_uids(void)
{
#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER
    // Refresh after tracking completes, including deferred scans.
    susfs_parse_priority_app_strings();
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    // Renew the sus path uid bitmap filter
    susfs_parse_sus_path_app_strings();
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH
}
