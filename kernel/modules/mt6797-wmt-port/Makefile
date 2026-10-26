obj-m += mt6797_wmt_soc.o
mt6797_wmt_soc-y := core/wmt_core.o core/wmt_ctrl.o core/wmt_func.o core/wmt_ic_soc.o core/wmt_lib.o core/wmt_conf.o core/stp_core.o core/psm_core.o core/btm_core.o core/dbg_core.o
mt6797_wmt_soc-y += linux/pri/wmt_dev.o linux/pri/wmt_exp.o linux/pri/stp_btif.o linux/pri/stp_exp.o linux/pri/stp_dbg.o
mt6797_wmt_soc-y += linux/pub/osal.o linux/pub/bgw_desense.o linux/pub/wmt_chrdev_wifi.o mt6797/mtk_wcn_consys_hw.o mt6797/wmt_plat_alps.o
mt6797_wmt_soc-y += wmt-native-support.o
mt6797_wmt_soc-y += wmt-native-hardware.o
mt6797_wmt_soc-y += wmt-native-power.o
ccflags-y += -I$(src)/linux/include -I$(src)/linux/pri/include -I$(src)/core/include -I$(src)/include -I$(src)/mt6797/include
ccflags-y += -I/mnt/c/Users/MSIK/Documents/ChatGPT/魅族Pro6刷安卓/sources/meizu-m685-port/drivers/misc/mediatek/connectivity/common/common_detect
ccflags-y += -I/mnt/c/Users/MSIK/Documents/ChatGPT/魅族Pro6刷安卓/sources/meizu-m685-port/drivers/misc/mediatek/include/mt-plat
ccflags-y += -I/mnt/c/Users/MSIK/Documents/ChatGPT/魅族Pro6刷安卓/sources/meizu-m685-port/drivers/misc/mediatek/include
ccflags-y += -I/mnt/c/Users/MSIK/Documents/ChatGPT/魅族Pro6刷安卓/sources/meizu-m685-port/drivers/misc/mediatek/include/mt-plat/mt6797/include
ccflags-y += -I/mnt/c/Users/MSIK/Documents/ChatGPT/魅族Pro6刷安卓/sources/meizu-m685-port/drivers/misc/mediatek/include/mt-plat/mt6797/include/mach
ccflags-y += -I/root/pro6-linux/mt6797-btif-port/inc
ccflags-y += -DWMT_PLAT_ALPS -DWMT_IDC_SUPPORT=0 -DWMT_CREATE_NODE_DYNAMIC=1 -DCONFIG_ARCH_MT6797
