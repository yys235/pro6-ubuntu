"""Use the migrated OSAL wakeup source in the MT6797 platform layer."""
from pathlib import Path
import re

path = Path('/root/pro6-linux/mt6797-wmt-port/mt6797/wmt_plat_alps.c')
source = path.read_text().replace('#include <linux/delay.h>',
                                  '#include <linux/delay.h>\n#include <linux/pinctrl/consumer.h>')
pattern = r'#ifdef CONFIG_PM_WAKELOCKS\n(.*?)#else\n(.*?)#endif'

def migrate(match):
    old = match.group()
    if 'static struct wakeup_source' in old:
        return 'static OSAL_WAKE_LOCK wmtWakeLock;'
    if 'wakeup_source_init' in old:
        return '''	strscpy((char *)wmtWakeLock.name, "wmtFuncCtrl", sizeof(wmtWakeLock.name));
	iret = osal_wake_lock_init(&wmtWakeLock);
	if (iret) {
		mtk_wcn_cmb_stub_unreg();
		return iret;
	}'''
    if 'wakeup_source_trash' in old:
        return '\tosal_wake_lock_deinit(&wmtWakeLock);'
    if '__pm_stay_awake' in old:
        return '\tosal_wake_lock(&wmtWakeLock);\n\tstatus = osal_wake_lock_count(&wmtWakeLock);'
    if '__pm_relax' in old:
        return '\tosal_wake_unlock(&wmtWakeLock);\n\tstatus = osal_wake_lock_count(&wmtWakeLock);'
    if 'status = wmtWakeLock.active' in old:
        return '\tstatus = osal_wake_lock_count(&wmtWakeLock);'
    raise AssertionError(old)

source, count = re.subn(pattern, migrate, source, flags=re.S)
assert count == 6, count
path.write_text(source)
