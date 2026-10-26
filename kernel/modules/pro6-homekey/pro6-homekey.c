// SPDX-License-Identifier: GPL-2.0
/* Apply homekey child to /pwrap@1000d000/pmic/keys via DT overlay. */
#include <linux/module.h>
#include <linux/of.h>

extern const char homekey_dtbo[];
extern const unsigned int homekey_dtbo_len;

static int overlay_id = -1;

static int __init pro6_homekey_init(void)
{
	int ret = of_overlay_fdt_apply(homekey_dtbo, homekey_dtbo_len,
				       &overlay_id, NULL);

	if (ret)
		pr_err("pro6_homekey: overlay apply failed: %d\n", ret);
	else
		pr_info("pro6_homekey: overlay applied, id=%d\n", overlay_id);
	return ret;
}

static void __exit pro6_homekey_exit(void)
{
	if (overlay_id >= 0)
		of_overlay_remove(&overlay_id);
}

module_init(pro6_homekey_init);
module_exit(pro6_homekey_exit);
MODULE_LICENSE("GPL");
