// SPDX-License-Identifier: GPL-2.0-only
/* Native HCI over the real MT6797 WMT/STP/BTIF transport. */
#include <linux/module.h>
#include <linux/firmware.h>
#include <linux/etherdevice.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/skbuff.h>
#include <linux/workqueue.h>
#include <net/bluetooth/bluetooth.h>
#include <net/bluetooth/hci_core.h>
#include "hci_uart.h" /* upstream H4 reassembly; no UART/TTY device is emulated */
#include "osal_typedef.h"
#include "stp_exp.h"
#include "wmt_exp.h"

struct pro6_bt {
    struct hci_dev *hdev;
    struct platform_device *parent;
    struct hci_uart h4;
    struct sk_buff *rx;
    struct sk_buff_head tx;
    struct delayed_work tx_work;
    spinlock_t rx_lock;
    bool running;
};
static struct pro6_bt *pro6_bt;

/* MT6797 vendor init sequence, using this phone's saved factory calibration.
 * Layout and opcodes: gemian 8cfe6596 drv_bt/{include/hci_stp.h,linux/hci_stp.c}.
 * These commands set volatile controller state; NVRAM is never written.
 */
static int pro6_setup(struct hci_dev *hdev)
{
    const struct firmware *fw;
    u8 address[6];
    int i, ret;
    ret = request_firmware_direct(&fw, "pro6/BT_Addr", &hdev->dev);
    if (ret) return ret;
    if (fw->size != 66 || !is_valid_ether_addr(fw->data)) {
        ret = -EINVAL;
        goto out;
    }
    for (i = 0; i < 6; i++) address[i] = fw->data[5 - i];
    ret = __hci_cmd_sync_status(hdev, 0xfc1a, 6, address, HCI_INIT_TIMEOUT);
    if (ret) goto out;
    ret = __hci_cmd_sync_status(hdev, 0xfc79, 6, fw->data + 12, HCI_INIT_TIMEOUT);
    if (ret) goto out;
    ret = __hci_cmd_sync_status(hdev, 0xfc93, 3, fw->data + 27, HCI_INIT_TIMEOUT);
    if (ret) goto out;
    ret = __hci_cmd_sync_status(hdev, 0xfc7a, 7, fw->data + 18, HCI_INIT_TIMEOUT);
    if (!ret) {
        u8 mask[8] = { 0x1f };
        struct hci_cp_write_le_host_supported host = { .le = 1, .simul = 0 };
        int probe;
        probe = __hci_cmd_sync_status(hdev, HCI_OP_WRITE_LE_HOST_SUPPORTED,
                                     sizeof(host), &host, HCI_INIT_TIMEOUT);
        bt_dev_info(hdev, "diagnostic early LE host support: %d", probe);
        probe = __hci_cmd_sync_status(hdev, HCI_OP_LE_SET_EVENT_MASK,
                                     sizeof(mask), mask, HCI_INIT_TIMEOUT);
        bt_dev_info(hdev, "diagnostic LE base event mask: %d", probe);
        for (i = 5; i <= 10; i++) {
            memset(mask, 0, sizeof(mask));
            mask[0] = 0x1f;
            mask[i / 8] |= BIT(i % 8);
            probe = __hci_cmd_sync_status(hdev, HCI_OP_LE_SET_EVENT_MASK,
                                         sizeof(mask), mask, HCI_INIT_TIMEOUT);
            bt_dev_info(hdev, "diagnostic LE event bit %d: %d", i, probe);
        }
    }
out:
    release_firmware(fw);
    return ret;
}

static const struct h4_recv_pkt pro6_rx_packets[] = {
    { H4_RECV_ACL, .recv = hci_recv_frame },
    { H4_RECV_SCO, .recv = hci_recv_frame },
    { H4_RECV_EVENT, .recv = hci_recv_frame },
};

static void pro6_rx(const UINT8 *data, INT32 length)
{
    struct pro6_bt *bt = READ_ONCE(pro6_bt);
    unsigned long flags;
    if (!bt || !READ_ONCE(bt->running) || length <= 0)
        return;
    spin_lock_irqsave(&bt->rx_lock, flags);
    bt->hdev->stat.byte_rx += length;
    bt->rx = h4_recv_buf(&bt->h4, bt->rx, data, length,
                          pro6_rx_packets, ARRAY_SIZE(pro6_rx_packets));
    if (IS_ERR(bt->rx)) {
        bt_dev_err(bt->hdev, "STP H4 reassembly failed: %ld", PTR_ERR(bt->rx));
        bt->hdev->stat.err_rx++;
        bt->rx = NULL;
    }
    spin_unlock_irqrestore(&bt->rx_lock, flags);
}

static void pro6_tx_ready(void)
{
    struct pro6_bt *bt = READ_ONCE(pro6_bt);
    if (bt && READ_ONCE(bt->running))
        mod_delayed_work(system_unbound_wq, &bt->tx_work, 0);
}

static void pro6_tx_work(struct work_struct *work)
{
    struct pro6_bt *bt = container_of(to_delayed_work(work), struct pro6_bt, tx_work);
    struct sk_buff *skb;
    int sent;
    while (READ_ONCE(bt->running) && (skb = skb_dequeue(&bt->tx))) {
        sent = mtk_wcn_stp_send_data(skb->data, skb->len, BT_TASK_INDX);
        if (sent == 0) {
            skb_queue_head(&bt->tx, skb);
            /* Resume callbacks normally kick TX; bounded-delay retries also
             * cover a resume racing the end of this worker invocation.
             */
            mod_delayed_work(system_unbound_wq, &bt->tx_work, msecs_to_jiffies(10));
            return;
        }
        if (sent != skb->len) {
            bt_dev_err(bt->hdev, "STP transmit failed: %d/%u", sent, skb->len);
            bt->hdev->stat.err_tx++;
        } else {
            bt->hdev->stat.byte_tx += sent;
            switch (skb->data[0]) {
            case HCI_COMMAND_PKT: bt->hdev->stat.cmd_tx++; break;
            case HCI_ACLDATA_PKT: bt->hdev->stat.acl_tx++; break;
            case HCI_SCODATA_PKT: bt->hdev->stat.sco_tx++; break;
            }
        }
        kfree_skb(skb);
    }
}

static int pro6_open(struct hci_dev *hdev)
{
    struct pro6_bt *bt = hci_get_drvdata(hdev);
    int ret;
    if (!mtk_wcn_wmt_func_on(WMTDRV_TYPE_BT))
        return -ENODEV;
    if (!mtk_wcn_stp_is_ready()) {
        ret = -EIO;
        goto off;
    }
    bt->h4.padding = 0;
    ret = mtk_wcn_stp_register_event_cb(BT_TASK_INDX, NULL);
    if (ret) goto off;
    ret = mtk_wcn_stp_register_if_rx(pro6_rx);
    if (ret) goto off;
    ret = mtk_wcn_stp_register_tx_event_cb(BT_TASK_INDX, pro6_tx_ready);
    if (ret) goto clear_rx;
    WRITE_ONCE(bt->running, true);
    mtk_wcn_stp_set_bluez(1);
    return 0;
clear_rx:
    mtk_wcn_stp_register_if_rx(NULL);
off:
    mtk_wcn_wmt_func_off(WMTDRV_TYPE_BT);
    return ret;
}

static int pro6_flush(struct hci_dev *hdev)
{
    struct pro6_bt *bt = hci_get_drvdata(hdev);
    cancel_delayed_work_sync(&bt->tx_work);
    skb_queue_purge(&bt->tx);
    return 0;
}

static int pro6_close(struct hci_dev *hdev)
{
    struct pro6_bt *bt = hci_get_drvdata(hdev);
    unsigned long flags;
    WRITE_ONCE(bt->running, false);
    /* WMT uses RCU for these callbacks, so unregister waits for RX/TX users. */
    mtk_wcn_stp_register_if_rx(NULL);
    mtk_wcn_stp_register_tx_event_cb(BT_TASK_INDX, NULL);
    pro6_flush(hdev);
    spin_lock_irqsave(&bt->rx_lock, flags);
    kfree_skb(bt->rx);
    bt->rx = NULL;
    spin_unlock_irqrestore(&bt->rx_lock, flags);
    mtk_wcn_stp_set_bluez(0);
    return mtk_wcn_wmt_func_off(WMTDRV_TYPE_BT) ? 0 : -EIO;
}

static int pro6_send(struct hci_dev *hdev, struct sk_buff *skb)
{
    struct pro6_bt *bt = hci_get_drvdata(hdev);
    u8 type = hci_skb_pkt_type(skb);
    if (!READ_ONCE(bt->running))
        return -ENETDOWN;
    if (type != HCI_COMMAND_PKT && type != HCI_ACLDATA_PKT && type != HCI_SCODATA_PKT)
        return -EINVAL;
    if (skb_cow_head(skb, 1))
        return -ENOMEM;
    *(u8 *)skb_push(skb, 1) = type;
    skb_queue_tail(&bt->tx, skb);
    mod_delayed_work(system_unbound_wq, &bt->tx_work, 0);
    return 0;
}

static int __init pro6_hci_init(void)
{
    struct device_node *node;
    struct pro6_bt *bt;
    int ret;
    if (!of_machine_is_compatible("meizu,pro6")) return -ENODEV;
    node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-consys");
    if (!node) return -ENODEV;
    bt = kzalloc(sizeof(*bt), GFP_KERNEL);
    if (!bt) { of_node_put(node); return -ENOMEM; }
    bt->parent = of_find_device_by_node(node);
    of_node_put(node);
    if (!bt->parent || !bt->parent->dev.driver) { ret = -EPROBE_DEFER; goto free; }
    bt->hdev = hci_alloc_dev();
    if (!bt->hdev) { ret = -ENOMEM; goto free; }
    bt->h4.hdev = bt->hdev;
    bt->hdev->bus = HCI_UART;
    bt->hdev->open = pro6_open;
    bt->hdev->close = pro6_close;
    bt->hdev->flush = pro6_flush;
    bt->hdev->send = pro6_send;
    bt->hdev->setup = pro6_setup;
    SET_HCIDEV_DEV(bt->hdev, &bt->parent->dev);
    hci_set_drvdata(bt->hdev, bt);
    spin_lock_init(&bt->rx_lock);
    skb_queue_head_init(&bt->tx);
    INIT_DELAYED_WORK(&bt->tx_work, pro6_tx_work);
    WRITE_ONCE(pro6_bt, bt);
    ret = hci_register_dev(bt->hdev);
    if (ret) {
        WRITE_ONCE(pro6_bt, NULL);
        hci_free_dev(bt->hdev);
        goto free;
    }
    pr_info("PRO6: native HCI registered over MT6797 STP/BTIF\n");
    return 0;
free:
    if (bt->parent) put_device(&bt->parent->dev);
    kfree(bt);
    return ret;
}

static void __exit pro6_hci_exit(void)
{
    struct pro6_bt *bt = pro6_bt;
    hci_unregister_dev(bt->hdev);
    cancel_delayed_work_sync(&bt->tx_work);
    skb_queue_purge(&bt->tx);
    kfree_skb(bt->rx);
    WRITE_ONCE(pro6_bt, NULL);
    hci_free_dev(bt->hdev);
    put_device(&bt->parent->dev);
    kfree(bt);
}
module_init(pro6_hci_init);
module_exit(pro6_hci_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PRO 6 native Bluetooth HCI over MT6797 WMT STP BTIF");
