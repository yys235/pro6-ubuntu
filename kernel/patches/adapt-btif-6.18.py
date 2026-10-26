"""Apply explicit Linux API migrations to the isolated BTIF port only."""
from pathlib import Path

root = Path('/root/pro6-linux/mt6797-btif-port')
for path in [*root.glob('*.c'), *root.glob('inc/*.h'), *root.glob('plat_inc/*.h')]:
    source = path.read_text()
    source = source.replace('struct timeval', 'struct btif_timeval')
    source = source.replace('do_gettimeofday(', 'btif_get_timeval(')
    path.write_text(source)
header = root / 'plat_inc/plat_common.h'
source = header.read_text()
marker = '#include <linux/kernel.h>'
assert marker in source
source = source.replace(marker, '''#include <linux/kernel.h>
#include <linux/timekeeping.h>
struct btif_timeval {
	time64_t tv_sec;
	long tv_usec;
};
static inline void btif_get_timeval(struct btif_timeval *value)
{
	struct timespec64 now;
	ktime_get_ts64(&now);
	value->tv_sec = now.tv_sec;
	value->tv_usec = now.tv_nsec / NSEC_PER_USEC;
}''')
header.write_text(source)
path = root / 'mtk_btif.c'
source = path.read_text()
source = source.replace('static int mtk_btif_remove(', 'static void mtk_btif_remove(')
start = source.index('static void mtk_btif_remove(struct platform_device *pdev)\n{')
end = source.index('\n}', start)
body = source[start:end]
assert body.count('\treturn 0;') == 1
source = source[:start] + body.replace('\treturn 0;', '') + source[end:]
source = source.replace('class_create(THIS_MODULE, p_btif_dev_name)', 'class_create(p_btif_dev_name)')
source = source.replace('static DRIVER_ATTR(flag, S_IRUGO | S_IWUSR, driver_flag_read, driver_flag_set);',
                        'static struct driver_attribute driver_attr_flag = __ATTR(flag, 0644, driver_flag_read, driver_flag_set);')
source = source.replace('dma_zalloc_coherent(dev,', 'dma_alloc_coherent(dev,')
source = source.replace('&p_vfifo->phy_addr, GFP_DMA | GFP_DMA32)',
                        '&p_vfifo->phy_addr, GFP_KERNEL | __GFP_ZERO)')
marker = 'static int mtk_btif_probe(struct platform_device *pdev)\n{'
assert source.count(marker) == 1
source = source.replace(marker, marker + '''
	int ret;
	ret = dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;
''')
source = source.replace('\thal_btif_clk_get_and_prepare(pdev);',
                        '''	ret = hal_btif_clk_get_and_prepare(pdev);
	if (ret) {
		g_btif[0].private_data = NULL;
		return ret;
	}''')
marker = '\ti_ret = driver_create_file(&mtk_btif_dev_drv.driver, &driver_attr_flag);'
assert source.count(marker) == 1
source = source.replace(marker, '''	if (!g_btif[0].private_data) {
		platform_driver_unregister(&mtk_btif_dev_drv);
		return -EPROBE_DEFER;
	}
''' + marker)
marker = 'static int BTIF_init(void)\n{'
assert source.count(marker) == 1
# Keep declarations first, then fail before registration or any MMIO access.
marker = '\tBTIF_DBG_FUNC("++\\n");\n\n/*Platform Driver initialization*/'
assert source.count(marker) == 1
source = source.replace(marker, '''	struct device_node *node;
	const char * const compatibles[] = {
		"mediatek,btif", "mediatek,btif_rx", "mediatek,btif_tx"
	};
	int n;
	for (n = 0; n < ARRAY_SIZE(compatibles); n++) {
		node = of_find_compatible_node(NULL, NULL, compatibles[n]);
		if (!node)
			return -ENODEV;
		of_node_put(node);
	}
''' + marker)
path.write_text(source)
# These functions were linked into the old monolithic vendor kernel. WMT now
# lives in a separate GPL module, so publish the existing implementations.
for filename, name in [('mtk_btif_exp.c', 'mtk_wcn_btif_parser_wmt_evt'),
                       ('mtk_btif.c', 'mtk_btif_rxd_be_blocked_flag_get')]:
    item = root / filename
    text = item.read_text()
    import re
    pattern = rf'((?:bool|int) {name}\(.*?\n\{{.*?\n\}})'
    text, count = re.subn(pattern, lambda m: m.group(1) + f'\nEXPORT_SYMBOL_GPL({name});', text, flags=re.S)
    assert count == 1, name
    item.write_text(text)
