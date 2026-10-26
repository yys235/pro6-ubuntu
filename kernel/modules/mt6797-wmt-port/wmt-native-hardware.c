// SPDX-License-Identifier: GPL-2.0-only
/* MT6797/PRO 6 hardware integration using native kernel providers.
 * Protocols: meizuosc/m685 MT6797 EMI, watchdog and MT6351 register sources.
 * No operations execute merely by linking this object.
 */
#include <linux/arm-smccc.h>
#include <linux/mutex.h>
#include <linux/firmware.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/sizes.h>
#include "wmt-native-hardware.h"

static DEFINE_MUTEX(wmt_reset_lock);
static struct reset_control *wmt_conn_reset;

int wmt_native_validate_platform(void)
{
	static const resource_size_t bases[] = { 0x18070000, 0x10007000, 0x10000000, 0x10006000 };
	static const resource_size_t sizes[] = { 0x200, 0x100, 0x2000, 0x1000 };
	struct device_node *node;
	struct platform_device *device;
	const struct firmware *config;
	struct resource resource;
	int i, ret = 0;
	if (!wmt_native_emi_base())
		return -ENODEV;
	node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");
	if (!node)
		return -ENODEV;
	for (i = 0; i < ARRAY_SIZE(bases); i++) {
		ret = of_address_to_resource(node, i, &resource);
		if (ret || resource.start != bases[i] || resource_size(&resource) != sizes[i]) {
			ret = -EINVAL;
			goto put_node;
		}
	}
	device = of_find_device_by_node(node);
	if (!device) {
		ret = -EPROBE_DEFER;
		goto put_node;
	}
	/* Pre-probe firmware caching against device would add devres to an
	 * unbound platform device and make driver core reject its later probe.
	 */
	ret = request_firmware_direct(&config, "WMT_SOC.cfg", NULL);
	if (!ret) {
		if (!config->size)
			ret = -EINVAL;
		release_firmware(config);
	}
	if (!ret) {
		struct reset_control *reset = of_reset_control_get_exclusive(node, "conn");
		if (IS_ERR(reset))
			ret = PTR_ERR(reset);
		else
			reset_control_put(reset);
	}
	if (!ret)
		ret = wmt_native_power_prepare(device);
	put_device(&device->dev);
put_node:
	of_node_put(node);
	if (ret)
		wmt_native_release_resources();
	return ret;
}

phys_addr_t wmt_native_emi_base(void)
{
	struct device_node *node;
	struct resource resource;
	int ret;
	if (!of_machine_is_compatible("meizu,pro6"))
		return 0;
	node = of_find_node_by_path("/reserved-memory/consys@b9600000");
	if (!node)
		return 0;
	ret = of_address_to_resource(node, 0, &resource);
	of_node_put(node);
	if (ret || resource.start != 0xb9600000 || resource_size(&resource) != SZ_2M)
		return 0;
	return resource.start;
}

int wmt_native_pmic_update(u16 reg, u32 mask, u32 value)
{
	struct device_node *node;
	struct platform_device *pmic;
	struct regmap *map;
	int ret;
	if (!of_machine_is_compatible("meizu,pro6") || mask != BIT(3) || (value & ~mask))
		return -EINVAL;
	if (reg != 0x0a0c && reg != 0x0a52 && reg != 0x0a98 && reg != 0x0a9a)
		return -EINVAL;
	node = of_find_compatible_node(NULL, NULL, "mediatek,mt6351");
	if (!node)
		return -ENODEV;
	pmic = of_find_device_by_node(node);
	of_node_put(node);
	if (!pmic)
		return -EPROBE_DEFER;
	map = dev_get_regmap(pmic->dev.parent, NULL);
	ret = map ? regmap_update_bits(map, reg, mask, value) : -EPROBE_DEFER;
	put_device(&pmic->dev);
	return ret;
}

int wmt_native_emi_set(u64 start, u64 end, int region, u32 permission)
{
	struct arm_smccc_res result;
	phys_addr_t base = wmt_native_emi_base();
	u32 expected = (5 << 21) | (5 << 18) | (5 << 15) | (5 << 12) | (5 << 9) | (5 << 3);
	if (!base || region != 19 || start != base + SZ_512K ||
	    end != base + SZ_1M - 1 || permission != expected)
		return -EINVAL;
	arm_smccc_smc(0x82000209, start, end, permission | (19U << 27),
		      0, 0, 0, 0, &result);
	if ((s32)result.a0)
		pr_err("WMT EMI protection SMC returned %d\n", (s32)result.a0);
	return (s32)result.a0;
}

int wmt_native_reset(int mask, int assert)
{
	struct device_node *node;
	int ret;
	if (mask != BIT(12) || (assert != 0 && assert != 1))
		return -EINVAL;
	mutex_lock(&wmt_reset_lock);
	if (!wmt_conn_reset) {
		node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");
		if (!node) {
			ret = -ENODEV;
			goto unlock;
		}
		wmt_conn_reset = of_reset_control_get_exclusive(node, "conn");
		of_node_put(node);
		if (IS_ERR(wmt_conn_reset)) {
			ret = PTR_ERR(wmt_conn_reset);
			wmt_conn_reset = NULL;
			goto unlock;
		}
	}
	ret = assert ? reset_control_assert(wmt_conn_reset) : reset_control_deassert(wmt_conn_reset);
unlock:
	mutex_unlock(&wmt_reset_lock);
	return ret;
}

void wmt_native_release_resources(void)
{
	wmt_native_power_release();
	mutex_lock(&wmt_reset_lock);
	reset_control_put(wmt_conn_reset);
	wmt_conn_reset = NULL;
	mutex_unlock(&wmt_reset_lock);
}
