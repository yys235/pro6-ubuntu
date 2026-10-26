"""Migrate WMT OS adaptation to standard Linux APIs; no Android wakelocks."""
from pathlib import Path
import re

root = Path('/root/pro6-linux/mt6797-wmt-port')
for item in root.rglob('*'):
    if item.suffix in ('.c', '.h'):
        text = item.read_text()
        text = text.replace('struct timeval', 'struct wmt_timeval')
        text = text.replace('do_gettimeofday(', 'wmt_get_real_timeval(')
        item.write_text(text)
path = root / 'linux/include/osal_typedef.h'
source = path.read_text()
old = '''#ifdef CONFIG_PM_WAKELOCKS
#include <linux/pm_wakeup.h>
#else
#include <linux/wakelock.h>
#endif'''
assert old in source
path.write_text(source.replace(old, '''#include <linux/pm_wakeup.h>
#include <linux/timekeeping.h>
struct wmt_timeval { time64_t tv_sec; long tv_usec; };
static inline void wmt_get_real_timeval(struct wmt_timeval *value)
{
	struct timespec64 now;
	ktime_get_real_ts64(&now);
	value->tv_sec = now.tv_sec;
	value->tv_usec = now.tv_nsec / NSEC_PER_USEC;
}'''))
path = root / 'linux/include/osal.h'
source = path.read_text()
old = '''	#ifdef CONFIG_PM_WAKELOCKS
	struct wakeup_source wake_lock;
	#else
	struct wake_lock wake_lock;
	#endif'''
assert old in source
path.write_text(source.replace(old, '\tstruct wakeup_source *wake_lock;'))
path = root / 'linux/pub/osal.c'
source = path.read_text()
functions = {
'osal_wake_lock_init': '''	if (!pLock)
		return -EINVAL;
	pLock->wake_lock = wakeup_source_register(NULL, (char *)pLock->name);
	return pLock->wake_lock ? 0 : -ENOMEM;''',
'osal_wake_lock_deinit': '''	if (!pLock)
		return -EINVAL;
	wakeup_source_unregister(pLock->wake_lock);
	pLock->wake_lock = NULL;
	return 0;''',
'osal_wake_lock': '''	if (!pLock || !pLock->wake_lock)
		return -EINVAL;
	__pm_stay_awake(pLock->wake_lock);
	return 0;''',
'osal_wake_unlock': '''	if (!pLock || !pLock->wake_lock)
		return -EINVAL;
	__pm_relax(pLock->wake_lock);
	return 0;''',
'osal_wake_lock_count': '''	unsigned long flags;
	int active;
	if (!pLock || !pLock->wake_lock)
		return -EINVAL;
	spin_lock_irqsave(&pLock->wake_lock->lock, flags);
	active = pLock->wake_lock->active;
	spin_unlock_irqrestore(&pLock->wake_lock->lock, flags);
	return active;''',
}
for name, body in functions.items():
    pattern = rf'INT32 {name}\(P_OSAL_WAKE_LOCK pLock\)\n\{{.*?\n\}}'
    source, count = re.subn(pattern, lambda m: f'INT32 {name}(P_OSAL_WAKE_LOCK pLock)\n{{\n{body}\n}}', source, flags=re.S)
    assert count == 1, name
old = '''	init_timer(timer);
	timer->function = pTimer->timeoutHandler;
	timer->data = (unsigned long)pTimer->timeroutHandlerData;'''
assert old in source
source = source.replace(old, '\ttimer_setup(timer, osal_timer_callback, 0);')
source = source.replace('INT32 osal_timer_create(P_OSAL_TIMER pTimer)', '''static void osal_timer_callback(struct timer_list *timer)
{
	P_OSAL_TIMER owner = container_of(timer, OSAL_TIMER, timer);
	owner->timeoutHandler(owner->timeroutHandlerData);
}

INT32 osal_timer_create(P_OSAL_TIMER pTimer)''')
source = source.replace('struct wmt_timeval now;', 'struct timespec64 now;')
source = source.replace('wmt_get_real_timeval(&now);', 'ktime_get_real_ts64(&now);')
source = source.replace('*usec = now.tv_usec;', '*usec = now.tv_nsec / NSEC_PER_USEC;')
source = source.replace('#include "osal.h"', '#include "osal.h"\n#include <linux/stacktrace.h>')
source = source.replace('return show_stack(pThread->pThread, NULL);', '''unsigned long entries[32];
	unsigned int count;
	if (!pThread || !pThread->pThread)
		return;
	count = stack_trace_save_tsk(pThread->pThread, entries, ARRAY_SIZE(entries), 0);
	stack_trace_print(entries, count, 0);''')
source = source.replace('del_timer_sync(', 'timer_delete_sync(').replace('del_timer(', 'timer_delete(')
thread_functions = {
    'osal_thread_create': '''    struct task_struct *task;
    if (!pThread) return -EINVAL;
    task = kthread_create(pThread->pThreadFunc, pThread->pThreadData, "%s", pThread->threadName);
    if (IS_ERR(task)) { pThread->pThread = NULL; return PTR_ERR(task); }
    pThread->pThread = task;
    return 0;''',
    'osal_thread_run': '''    if (!pThread || IS_ERR_OR_NULL(pThread->pThread)) return -EINVAL;
    wake_up_process(pThread->pThread);
    return 0;''',
    'osal_thread_stop': '''    struct task_struct *task;
    if (!pThread) return -EINVAL;
    /* stop + destroy must not call kthread_stop twice on a dead task. */
    task = xchg(&pThread->pThread, NULL);
    if (!task) return 0;
    if (IS_ERR(task)) return PTR_ERR(task);
    return kthread_stop(task);''',
    'osal_thread_destroy': '''    return osal_thread_stop(pThread);''',
}
for name, body in thread_functions.items():
    pattern = rf'INT32 {name}\(P_OSAL_THREAD pThread\)\n\{{.*?\n\}}'
    source, count = re.subn(pattern, lambda m: f'INT32 {name}(P_OSAL_THREAD pThread)\n{{\n{body}\n}}',
                            source, flags=re.S)
    assert count == 1, name
path.write_text(source)
