/* Optional policy calls from ReSukiSU 63ad1ea3/selinux/sepolicy.c. */
#include "sepolicy.h"
#ifdef CONFIG_KSU_SUSFS
extern int susfs_add_sus_avd_allowed_by_type(u32 s_type, u32 t_type, u32 c_type, u32 orig_avd_allowed);
extern int susfs_add_sus_type(const char *secctx, u32 type_value);
#endif
void compat_avd_hook(void)
{
#ifdef CONFIG_KSU_SUSFS
        susfs_add_sus_avd_allowed_by_type(src->value, tgt->value, cls->value, node->datum.u.data);
#endif // #ifdef CONFIG_KSU_SUSFS
}
void compat_type_hook(void)
{
#ifdef CONFIG_KSU_SUSFS
    susfs_add_sus_type(type_name, type->value);
#endif // #ifdef CONFIG_KSU_SUSFS
}
