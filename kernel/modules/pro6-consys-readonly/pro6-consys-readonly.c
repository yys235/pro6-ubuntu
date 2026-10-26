// SPDX-License-Identifier: GPL-2.0-only
/* Diagnostic only: no register write, power change, reset or EMI SET call. */
#include <linux/arm-smccc.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/reset.h>

static int __init pro6_cons_stage_read(void)
{
    struct device_node *node;
    struct resource resource;
    struct reset_control *reset;
    struct arm_smccc_res result;
    void __iomem *spm;
    unsigned int offsets[] = { 0x378, 0x3b8 };
    int i, ret;
    if (!of_machine_is_compatible("meizu,pro6"))
        return -ENODEV;
    node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");
    if (!node)
        return -ENODEV;
    ret = of_address_to_resource(node, 3, &resource);
    if (ret || resource.start != 0x10006000 || resource_size(&resource) != 0x1000) {
        ret = -EINVAL;
        goto put;
    }
    /* Acquiring/releasing an exclusive reset handle does not assert it. */
    reset = of_reset_control_get_exclusive(node, "conn");
    if (IS_ERR(reset)) {
        ret = PTR_ERR(reset);
        goto put;
    }
    reset_control_put(reset);
    pr_info("PRO6-CONSYS-RO: native CONMCU reset handle acquired/released\n");
    spm = ioremap(resource.start, resource_size(&resource));
    if (!spm) { ret = -ENOMEM; goto put; }
    pr_info("PRO6-CONSYS-RO: SPM ctrl32c=%08x status180=%08x status184=%08x\n",
            readl(spm + 0x32c), readl(spm + 0x180), readl(spm + 0x184));
    iounmap(spm);
    /* Exact vendor READ ABI. Region19 address bounds and access permission. */
    for (i = 0; i < ARRAY_SIZE(offsets); i++) {
        arm_smccc_smc(0x82000208, offsets[i], 0, 0, 0, 0, 0, 0, &result);
        pr_info("PRO6-CONSYS-RO: EMI READ offset=%x returned=%016lx\n",
                offsets[i], result.a0);
    }
    ret = 0;
put:
    of_node_put(node);
    return ret;
}
static void __exit pro6_cons_stage_exit(void) { }
module_init(pro6_cons_stage_read);
module_exit(pro6_cons_stage_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PRO 6 CONNSYS read-only preflight; no power/reset/EMI writes");
