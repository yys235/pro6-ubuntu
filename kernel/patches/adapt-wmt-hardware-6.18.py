"""Connect vendor call sites to guarded native hardware operations."""
from pathlib import Path

root = Path('/root/pro6-linux/mt6797-wmt-port')
path = root / 'mt6797/mtk_wcn_consys_hw.c'
source = path.read_text()
import re
source = source.replace('#include "osal_typedef.h"', '#include "osal_typedef.h"\n#include "wmt-native-hardware.h"')
source = source.replace('pmic_set_register_value(', 'WMT_SET_PMIC(')
source = source.replace('emi_mpu_set_region_protection(', 'WMT_SET_EMI(')
source = source.replace('mtk_wdt_swsysret_config(', 'WMT_SET_RESET(')
# The old conn clock actually represented an MTCMOS power domain. Use
# the source-verified native power sequence rather than a dummy clock.
clock_get = '''	clk_scp_conn_main = devm_clk_get(&pdev->dev, "conn");
	if (IS_ERR(clk_scp_conn_main)) {
		WMT_PLAT_ERR_FUNC("[CCF]cannot get clk_scp_conn_main clock.\\n");
		return PTR_ERR(clk_scp_conn_main);
	}
	WMT_PLAT_DBG_FUNC("[CCF]clk_scp_conn_main=%p\\n", clk_scp_conn_main);'''
assert source.count(clock_get) == 1
source = source.replace(clock_get, '''	int ret = wmt_native_power_prepare(pdev);
	if (ret)
		return ret;''')
assert source.count('clk_prepare_enable(clk_scp_conn_main)') >= 2
source = source.replace('iRet = clk_prepare_enable(clk_scp_conn_main);',
                        'iRet = wmt_native_power(true);\n\t\tif (iRet) return iRet;')
source = source.replace('clk_disable_unprepare(clk_scp_conn_main);', 'WMT_SET_POWER(false);')
# Abort before accessing an unpowered CONNSYS bank if a rail operation fails.
source = re.sub(r'(?m)^([\t ]*)regulator_set_voltage\(([^;]+)\);',
                r'\1WMT_REGULATOR_CALL(regulator_set_voltage(\2));', source)
pattern = (r'if \((regulator_(?:enable|disable)\(reg_\w+\))\)\n'
           r'\s+WMT_PLAT_\w+_FUNC\([^\n]+\);'
           r'(?:\n\s+else\n\s+WMT_PLAT_\w+_FUNC\([^\n]+\);)?')
source, count = re.subn(pattern, r'WMT_REGULATOR_CALL(\1);', source)
assert count == 7, count
source = re.sub(r'(?m)^([\t ]*)regulator_disable\((reg_\w+)\);',
                r'\1WMT_REGULATOR_CALL(regulator_disable(\2));', source)
# The old unsigned retry counter wrapped on exhaustion and could continue
# with an incorrect nonzero chip ID. Never write the MCU bank after that.
source = source.replace('if ((0 == retry) || (0 == consysHwChipId)) {',
                        'if (consysHwChipId != 0x0279) {')
marker = '\t\t/*13.{default no need}update ROMDEL/PATCH RAM DELSEL if needed 0x18070114 */'
assert marker in source
source = source.replace(marker, '\t\tif (consysHwChipId != 0x0279) return -ENODEV;\n'
    '\t\tpr_info("WMT: native CONNSYS ROM ID=%08x\\n", consysHwChipId);\n' + marker)
old = '''	iRet += mtk_wcn_consys_hw_reg_ctrl(1, co_clock_type);
	iRet += mtk_wcn_consys_hw_gpio_ctrl(1);'''
assert source.count(old) == 1
source = source.replace(old, '''	iRet = mtk_wcn_consys_hw_reg_ctrl(1, co_clock_type);
	if (iRet) return iRet;
	iRet = mtk_wcn_consys_hw_gpio_ctrl(1);
	if (iRet) {
		int off;
		mtk_wcn_consys_hw_gpio_ctrl(0);
		off = mtk_wcn_consys_hw_reg_ctrl(0, co_clock_type);
		if (off) pr_err("WMT: GPIO init failed, power rollback also failed: %d\\n", off);
		return iRet;
	}''')
# A failed regulator lookup is ERR_PTR, never NULL. Probe must fail before
# any power operation, and devres releases partial acquisitions on failure.
for rail in ['VCN18', 'VCN28', 'VCN33_BT', 'VCN33_WIFI']:
    pattern = (rf'reg_{rail} = regulator_get\(&pdev->dev, "([^"]+)"\);\n'
               rf'\tif \(!reg_{rail}\)\n\t\tWMT_PLAT_ERR_FUNC\([^\n]+\);')
    def regulator(match):
        return (f'reg_{rail} = devm_regulator_get(&pdev->dev, "{match[1]}");\n'
                f'\tif (IS_ERR(reg_{rail}))\n\t\treturn PTR_ERR(reg_{rail});')
    source, count = re.subn(pattern, regulator, source)
    assert count == 1, rail
# GPS LNA pin states are optional for the integrated Wi-Fi/BT data paths.
# GPS callers already reject a NULL pinctrl; retain real errors if present.
source = source.replace('''	if (IS_ERR(consys_pinctrl)) {
		WMT_PLAT_ERR_FUNC("cannot find consys pinctrl.\\n");
		return PTR_ERR(consys_pinctrl);
	}''', '''	if (IS_ERR(consys_pinctrl)) {
		if (PTR_ERR(consys_pinctrl) != -ENODEV)
			return PTR_ERR(consys_pinctrl);
		consys_pinctrl = NULL;
	}''')
marker = '\tnode = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");'
assert source.count(marker) >= 1
# Initialize only from this phone's already reserved, verified EMI region.
source = source.replace(marker, '''	gConEmiPhyBase = wmt_native_emi_base();
	if (!gConEmiPhyBase)
		return -ENODEV;
''' + marker, 1)
# A registered platform_driver does not imply a successful device probe.
# Require the real rails/power provider before touching EMI protection/remap.
start = source.index('static INT32 mtk_wmt_probe(struct platform_device *pdev)\n{')
end = source.index('static void mtk_wmt_remove', start)
probe = source[start:end]
assert probe.count('\treturn 0;') == 1
probe = probe.replace('\treturn 0;', '\tplatform_set_drvdata(pdev, &conn_reg);\n\treturn 0;')
source = source[:start] + probe + source[end:]
start = source.index('INT32 mtk_wcn_consys_hw_init(void)\n{')
end = source.index('UINT8 *mtk_wcn_consys_emi_virt_addr_get', start)
source = source[:start] + '''static bool pro6_consys_driver_registered;

static void pro6_consys_unregister(void)
{
	if (!pro6_consys_driver_registered) return;
	platform_driver_unregister(&mtk_wmt_dev_drv);
	pro6_consys_driver_registered = false;
}

static void pro6_consys_unmap(void)
{
	if (pEmibaseaddr) iounmap(pEmibaseaddr);
	pEmibaseaddr = NULL;
	if (conn_reg.mcu_base) iounmap((void __iomem *)conn_reg.mcu_base);
	if (conn_reg.ap_rgu_base) iounmap((void __iomem *)conn_reg.ap_rgu_base);
	if (conn_reg.topckgen_base) iounmap((void __iomem *)conn_reg.topckgen_base);
	if (conn_reg.spm_base) iounmap((void __iomem *)conn_reg.spm_base);
	memset(&conn_reg, 0, sizeof(conn_reg));
}

INT32 mtk_wcn_consys_hw_init(void)
{
	struct device_node *node;
	struct platform_device *device;
	u32 address, previous;
	int ret;
	gConEmiPhyBase = wmt_native_emi_base();
	if (!gConEmiPhyBase) return -ENODEV;
	node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");
	if (!node) return -ENODEV;
	device = of_find_device_by_node(node);
	if (!device) { ret = -EPROBE_DEFER; goto put_node; }
	ret = platform_driver_register(&mtk_wmt_dev_drv);
	if (ret) goto put_device;
	pro6_consys_driver_registered = true;
	if (!device->dev.driver || platform_get_drvdata(device) != &conn_reg) {
		ret = -ENODEV;
		goto unregister;
	}
	conn_reg.mcu_base = (SIZE_T)of_iomap(node, 0);
	conn_reg.ap_rgu_base = (SIZE_T)of_iomap(node, 1);
	conn_reg.topckgen_base = (SIZE_T)of_iomap(node, 2);
	conn_reg.spm_base = (SIZE_T)of_iomap(node, 3);
	if (!conn_reg.mcu_base || !conn_reg.ap_rgu_base ||
	    !conn_reg.topckgen_base || !conn_reg.spm_base) {
		ret = -ENOMEM;
		goto unregister;
	}
	ret = wmt_native_emi_set(gConEmiPhyBase + SZ_1M / 2,
		gConEmiPhyBase + SZ_1M - 1, 19,
		SET_ACCESS_PERMISSON(FORBIDDEN, FORBIDDEN, FORBIDDEN, FORBIDDEN,
		FORBIDDEN, NO_PROTECTION, FORBIDDEN, NO_PROTECTION));
	if (ret) goto unregister;
	pEmibaseaddr = ioremap(gConEmiPhyBase + SZ_1M / 2, CONSYS_EMI_MEM_SIZE);
	if (!pEmibaseaddr) { ret = -ENOMEM; goto unregister; }
	address = ((gConEmiPhyBase & 0xFFF00000) >> 20) | 0x1000;
	previous = readl((void __iomem *)(conn_reg.topckgen_base + CONSYS_EMI_MAPPING_OFFSET));
	writel((previous & ~0x1fffU) | address,
		(void __iomem *)(conn_reg.topckgen_base + CONSYS_EMI_MAPPING_OFFSET));
	memset_io(pEmibaseaddr, 0, CONSYS_EMI_MEM_SIZE);
	ret = 0;
	goto put_device;
unregister:
	pro6_consys_unregister();
	pro6_consys_unmap();
	wmt_native_release_resources();
put_device:
	put_device(&device->dev);
put_node:
	of_node_put(node);
	return ret;
}

INT32 mtk_wcn_consys_hw_deinit(void)
{
	pro6_consys_unregister();
	pro6_consys_unmap();
	wmt_native_release_resources();
	return 0;
}

''' + source[end:]
source = '#include <linux/of_platform.h>\n' + source
path.write_text(source)
path = root / 'linux/pri/wmt_dev.c'
source = path.read_text()
source = '#include "wmt-native-hardware.h"\n' + source
marker = '\tstp_drv_init();'
assert source.count(marker) == 1
source = source.replace(marker, '''	ret = wmt_native_validate_platform();
	if (ret) {
		pr_err("WMT: platform/firmware admission failed: %d\\n", ret);
		return ret;
	}
''' + marker)
marker = '\twmt_lib_deinit();'
assert marker in source
source = source.replace(marker, marker + '\n\twmt_native_release_resources();')
path.write_text(source)
path = root / 'mt6797/wmt_plat_alps.c'
source = path.read_text()
source = '#include "wmt-native-hardware.h"\n' + source
for index, name in enumerate(['gps_lna_init', 'gps_lna_oh', 'gps_lna_ol'], 2):
    assert source.count(f'if (NULL == {name}) {{') == 1
    source = source.replace(f'if (NULL == {name}) {{', f'if (IS_ERR({name})) {{')
    source, count = re.subn(rf'(if \(IS_ERR\({name}\)\) \{{\n[^\n]+\n)\t\treturn -{index};',
                    rf'\1\t\treturn PTR_ERR({name});', source)
    assert count == 1
source, count = re.subn(r'(?m)^\s*pinctrl_select_state\(consys_pinctrl, (gps_lna_\w+)\);',
                r'\n\t\tWMT_REGULATOR_CALL(pinctrl_select_state(consys_pinctrl, \1));', source)
assert count == 3
marker = '\tWMT_PLAT_DBG_FUNC("WMT-PLAT: ALPS platform init (%d)\\n", iret);\n\n\treturn 0;'
assert source.count(marker) == 2
source = source.replace(marker, marker.replace('return 0;', 'return iret;'))
path.write_text(source)
