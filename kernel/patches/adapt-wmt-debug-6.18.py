"""Update the WMT debug netlink registration and ARM64 MMIO mapping API."""
from pathlib import Path

root = Path('/root/pro6-linux/mt6797-wmt-port')
for path in root.rglob('*.c'):
    source = path.read_text().replace('ioremap_nocache(', 'ioremap(')
    source = source.replace('#include <asm/memblock.h>', '#include <linux/memblock.h>')
    path.write_text(source)
path = root / 'linux/pri/stp_dbg.c'
source = path.read_text().replace('\t.id = GENL_ID_GENERATE,\n', '')
old = '\tif (genl_register_family_with_ops(&stp_dbg_gnl_family, stp_dbg_gnl_ops_array) != 0)'
assert old in source
source = source.replace(old, '''	stp_dbg_gnl_family.ops = stp_dbg_gnl_ops_array;
	stp_dbg_gnl_family.n_ops = ARRAY_SIZE(stp_dbg_gnl_ops_array);
	stp_dbg_gnl_family.module = THIS_MODULE;
	if (genl_register_family(&stp_dbg_gnl_family) != 0)''')
path.write_text(source)
path = root / 'mt6797/mtk_wcn_consys_hw.c'
source = path.read_text()
source = source.replace('#include <linux/delay.h>', '#include <linux/delay.h>\n#include <linux/pinctrl/consumer.h>')
source = source.replace('static INT32 mtk_wmt_remove(struct platform_device *pdev);',
                        'static void mtk_wmt_remove(struct platform_device *pdev);')
source = source.replace('static INT32 mtk_wmt_remove(struct platform_device *pdev)\n{\n\treturn 0;\n}',
                        'static void mtk_wmt_remove(struct platform_device *pdev)\n{\n}')
path.write_text(source)
