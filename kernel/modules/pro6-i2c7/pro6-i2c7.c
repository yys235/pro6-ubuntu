// SPDX-License-Identifier: GPL-2.0
/* PRO6: enable I2C7 (0x11010000, GPU PM bus) via devicetree overlay
 * so the RT5735 external VGPU buck at addr 0x1c becomes reachable. */
#include <linux/module.h>
#include <linux/of.h>

extern const char i2c7_dtbo[];
extern const unsigned int i2c7_dtbo_len;

static int overlay_id = -1;

static int __init pro6_i2c7_init(void)
{
	int ret = of_overlay_fdt_apply(i2c7_dtbo, i2c7_dtbo_len, &overlay_id, NULL);
	if (ret) {
		pr_err("pro6_i2c7: overlay apply failed: %d\n", ret);
		return ret;
	}
	pr_info("pro6_i2c7: overlay applied, id=%d\n", overlay_id);
	return 0;
}

static void __exit pro6_i2c7_exit(void)
{
	if (overlay_id >= 0)
		of_overlay_remove(&overlay_id);
}

module_init(pro6_i2c7_init);
module_exit(pro6_i2c7_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PRO6 I2C7 enable overlay");
