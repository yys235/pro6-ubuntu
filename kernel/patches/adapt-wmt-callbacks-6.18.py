"""Make STP direct HCI callback removal wait for in-flight users."""
from pathlib import Path
import re

path = Path('/root/pro6-linux/mt6797-wmt-port/linux/pri/stp_exp.c')
source = '#include <linux/rcupdate.h>\n' + path.read_text()
source = source.replace('static MTK_WCN_STP_IF_RX stp_if_rx;',
                        'static MTK_WCN_STP_IF_RX __rcu stp_if_rx;')
for name in ['event_callback_tbl', 'tx_event_callback_tbl']:
    source = source.replace(f'static MTK_WCN_STP_EVENT_CB {name}',
                            f'static MTK_WCN_STP_EVENT_CB __rcu {name}')

def replace_function(name, body):
    global source
    pattern = rf'(^((?:static )?INT32 {name}\([^\n]*\))\n)\{{.*?^\}}'
    source, count = re.subn(pattern, lambda m: m[1] + '{\n' + body + '\n}',
                            source, count=1, flags=re.M | re.S)
    assert count == 1, name

replace_function('mtk_wcn_sys_if_rx', '''    MTK_WCN_STP_IF_RX callback;
    int ret = -ENODEV;
    rcu_read_lock();
    callback = rcu_dereference(stp_if_rx);
    if (callback) { callback(data, size); ret = 0; }
    rcu_read_unlock();
    return ret;''')
replace_function('mtk_wcn_sys_event_set', '''    MTK_WCN_STP_EVENT_CB callback;
    if (function_type >= MTKSTP_MAX_TASK_NUM) return -EINVAL;
    rcu_read_lock();
    callback = rcu_dereference(event_callback_tbl[function_type]);
    if (callback) callback();
    rcu_read_unlock();
    return 0;''')
replace_function('mtk_wcn_sys_event_tx_resume', '''    int type;
    MTK_WCN_STP_EVENT_CB callback;
    rcu_read_lock();
    for (type = 0; type < MTKSTP_MAX_TASK_NUM; type++) {
        callback = rcu_dereference(tx_event_callback_tbl[type]);
        if (callback) callback();
    }
    rcu_read_unlock();
    return 0;''')
assert source.count('\tstp_if_rx = func;') == 1
source = source.replace('\tstp_if_rx = func;',
    '\trcu_assign_pointer(stp_if_rx, func);\n\tif (!func) synchronize_rcu();')
for name in ['event_callback_tbl', 'tx_event_callback_tbl']:
    statement = rf'\b{name}\[type\] = func;'
    replacement = '{\n\t\trcu_assign_pointer(' + name + '[type], func);\n' + \
                  '\t\tif (!func) synchronize_rcu();\n\t}'
    source, count = re.subn(statement, lambda match: replacement, source)
    assert count == 1, name
source = source.replace('if (type < MTKSTP_MAX_TASK_NUM)',
                        'if (type >= 0 && type < MTKSTP_MAX_TASK_NUM)')
source = source.replace('event_callback_tbl[type] != 0x0',
                        'rcu_access_pointer(event_callback_tbl[type]) != NULL')
path.write_text(source)
