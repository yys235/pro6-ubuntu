// SPDX-License-Identifier: GPL-2.0-only
/* Only CONNSYS: MT6797 CCF power sequence with bounded acknowledgements. */
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/mfd/syscon.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include "wmt-native-hardware.h"
#include "wmt-conn-sequence.h"

static DEFINE_MUTEX(conn_power_lock);
static void __iomem *conn_spm;
static struct regmap *conn_infra;

int wmt_native_power_prepare(struct platform_device *device)
{
    struct device_node *spm_node;
    struct resource resource;
    int ret = 0;
    mutex_lock(&conn_power_lock);
    if (conn_spm)
        goto unlock;
    if (!of_machine_is_compatible("meizu,pro6")) {
        ret = -ENODEV;
        goto unlock;
    }
    /* The generic provider must be disabled: it has not been ported for
     * this board. Never race another power driver over the same SPM bank.
     */
    spm_node = of_parse_phandle(device->dev.of_node, "mediatek,scpsys", 0);
    if (!spm_node) {
        ret = -ENODEV;
        goto unlock;
    }
    ret = of_address_to_resource(spm_node, 0, &resource);
    if (ret || of_device_is_available(spm_node) ||
        !of_device_is_compatible(spm_node, "mediatek,mt6797-scpsys") ||
        resource.start != 0x10006000 || resource_size(&resource) != 0x1000) {
        ret = -EINVAL;
        of_node_put(spm_node);
        goto unlock;
    }
    of_node_put(spm_node);
    conn_infra = syscon_regmap_lookup_by_phandle(device->dev.of_node, "mediatek,infracfg");
    if (IS_ERR(conn_infra)) {
        ret = PTR_ERR(conn_infra);
        conn_infra = NULL;
        goto unlock;
    }
    conn_spm = ioremap(resource.start, resource_size(&resource));
    if (!conn_spm) {
        conn_infra = NULL;
        ret = -ENOMEM;
    }
unlock:
    mutex_unlock(&conn_power_lock);
    return ret;
}

static int conn_write(void *context, int space, unsigned int offset, unsigned int value)
{
    if (space != WMT_CONN_SPM || offset != 0 || value != 0x0b160001)
        return -EINVAL;
    writel(value, conn_spm + offset);
    return 0;
}

static int conn_update(void *context, int space, unsigned int offset,
                       unsigned int mask, unsigned int value)
{
    u32 previous;
    if (value & ~mask)
        return -EINVAL;
    if (space == WMT_CONN_INFRA && offset == 0x220 && mask == (BIT(17) | BIT(18)))
        return regmap_update_bits(conn_infra, offset, mask, value);
    if (space != WMT_CONN_SPM || offset != 0x32c || mask & ~GENMASK(4, 0))
        return -EINVAL;
    previous = readl(conn_spm + offset);
    writel((previous & ~mask) | value, conn_spm + offset);
    return 0;
}

static int conn_poll(void *context, int space, unsigned int offset,
                     unsigned int mask, unsigned int expected)
{
    u32 value;
    if (space == WMT_CONN_INFRA && offset == 0x228 && mask == (BIT(17) | BIT(18)))
        return regmap_read_poll_timeout(conn_infra, offset, value,
                                       (value & mask) == expected, 10, 100000);
    if (space != WMT_CONN_SPM || (offset != 0x180 && offset != 0x184) || mask != BIT(1))
        return -EINVAL;
    return readl_poll_timeout(conn_spm + offset, value,
                              (value & mask) == expected, 10, 100000);
}

int wmt_native_power(bool on)
{
    struct wmt_conn_io io = { NULL, conn_write, conn_update, conn_poll };
    int ret;
    mutex_lock(&conn_power_lock);
    if (!conn_spm || !conn_infra) {
        ret = -ENODEV;
        goto unlock;
    }
    ret = wmt_conn_set_power(&io, on);
    if (ret)
        pr_err("WMT: CONNSYS power %s failed: %d (ctrl=%08x ack=%08x/%08x)\n",
               on ? "on" : "off", ret, readl(conn_spm + 0x32c),
               readl(conn_spm + 0x180), readl(conn_spm + 0x184));
unlock:
    mutex_unlock(&conn_power_lock);
    return ret;
}

void wmt_native_power_release(void)
{
    mutex_lock(&conn_power_lock);
    if (conn_spm)
        iounmap(conn_spm);
    conn_spm = NULL;
    conn_infra = NULL;
    mutex_unlock(&conn_power_lock);
}
