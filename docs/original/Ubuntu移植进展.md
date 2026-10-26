# 魅族 PRO 6 原生 Ubuntu 移植

2026-10-19：原生 Ubuntu 已启动，基础功能修复仍在进行。

- Ubuntu 26.04.1 LTS ARM64，真实 systemd PID 1。
- Linux 6.18.57 #13，自行移植 MT6797 的启动、USB、eMMC、PMIC、电池及无线基础支持。
- 8 个 Cortex-A53 核心在线，可用内存 3654 MiB；A72 两核暂未启用。
- 根文件系统位于 eMMC userdata 的 /pro6-ubuntu，通过 initramfs 切换为真正的系统根目录。
- 原生 USB RNDIS、OpenSSH、APT、Python 3.14.4 已实测。已移除 Android ADB 运行时。联网目前经电脑 SSH SOCKS 隧道。
- 当前 v20 boot 镜像 SHA256：86537bab8ce3c67348a92d1114ee627b1eff9b9e75ff16493528f1f2ab98ef45，写入后整分区 cmp 通过。
- recovery 保留可启动的 v9 Ubuntu 实验镜像；原厂分区备份在 device-backup。

## 尚未完成的硬件适配

屏幕已通过 simpledrm 与 DSI 命令模式刷新程序显示 Phosh 0.54 手机界面，替换旧 Xfce 会话。桌面和刷新服务自动启动；使用软件渲染及最多30帧/秒刷新，仍依赖引导程序初始化显示控制器。

触控芯片 Synaptics S3718AR 由上游 RMI4 驱动接入 Wayland/libinput。用户确认触控正常。Stevia 键盘自动尺寸问题已修复，用户确认输入和退格正常；文件管理器按手机布局运行。FUSE 内建，文件门户失败已消除。

MT6351 E2 PWRAP、MFD/IRQ、RTC 已接管，RTC 校时和十秒闹钟中断测试通过。原生只读 BQ27532 驱动接入 power_supply/UPower，真实电量、电压、电流、温度和容量可读，电池警告图标已恢复正常；重新开机后自动加载。

MT6351 BBPU 关机路径已接入，用户确认拔 USB 后能保持关机；接 USB 会自动开机，原生关机充电界面尚未实现。原 Android 数据已清理，custom/system/cache 已 discard，保留硬件固件和校准分区。

Wi-Fi、蓝牙、音频、相机、GPU 加速、主动充电参数管理与休眠仍未完成。BlueZ 已安装，但尚无 HCI 控制器；无线驱动仍需移植。现有电池驱动不改动充电参数、校准和闪存。内核不能通过 Ubuntu 通用内核包替换，电池外部模块也需与内核构建保持匹配。eMMC 暂用 25 MHz 保守模式。

无线基础进展：内建 Bluetooth/LE/VHCI、cfg80211 与 rfkill。四条 MT6351 无线电源及 BTIF/DMA 驱动随启动加载；新版 BTIF 的两项 WMT 导出已部署。WMT 模块现已链接通过，符号缺失为 0。v20 增加 CONSYS 资源和原生 TOPRGU 复位，实机只读取得/释放 CONMCU 复位句柄成功，EMI READ SMC 返回正常。原生 CONNSYS 供电序列已接入并通过离线正常/超时检查，但尚未执行硬件通电。WMT 因未安装匹配固件而按启动前检查退出；当前仍无可扫描网卡或蓝牙控制器。官方 PRO 6 固件下载中，详情见 experiment/无线驱动移植进展.md。

## 连接

在此目录执行 .\Connect-Ubuntu.ps1；它通过原生 USB 网络直接 SSH 连接 192.168.76.1、校准系统时间，并打开终端及 SOCKS 代理。手机网络程序可使用 socks5h://127.0.0.1:1080。APT 示例：

    apt-get -o Acquire::http::Proxy=socks5h://127.0.0.1:1080 update

## 实机证据

当前结果与未通过项见 evidence/基础功能测试结果.md，以及 rtc-v15-set-read.txt、rtc-alarm-v15.json、battery-native-v16.txt/png、poweroff-v16-result.txt。以下为早期阶段证据。

- evidence/ubuntu-default-boot-install.txt：写入和整分区读回校验。
- evidence/ubuntu-default-boot-first.txt：正常启动后的内核、Ubuntu、PID1、挂载、内存和 CPU。
- evidence/ubuntu-v9-fullmem-live.txt：完整内存恢复模式验证。
- evidence/fullmem-reservation-validation.json：实际原厂内存保留区覆盖校验。
- experiment/verify-native-memory.py：8 核各自固定亲和性后的内存页读写检查，恢复和正常启动均通过。

原始研究来源和下载校验保存在 sources、evidence 与各镜像 JSON 中。MT6797 参考移植来自 https://github.com/ixoo/gemini-pda-mainline ，固定提交 598040b5881d9d17d144dfc07fda0ea138e5e9db；它不是 PRO 6 的完整硬件支持包。

## 2026-10-19 16:37 后续实机验证（以本节为准，早期记录保留）

- 当前是 Ubuntu 26.04.1 / Linux 6.18.57 #14，v22 启动镜像 ubuntu-gps-gpio-v22.img。镜像 SHA256 ab0fe1a11b2006618f0cd5b978f1d99dafea28eb88dcdc1765c12cc7d945bcb1。
- 官方 PRO6 Flyme 8.0.5.0A 的无线固件已完成来源、ZIP MD5、文件 SHA256 校验并部署；只提取硬件固件，没有恢复 Android 系统。
- WMT 已通过真实 CONNSYS 上下电、ROM 补丁下载和三轮 64 字节随机数据回环；见 evidence/wmt-v22-three-cycle-data-loopback.txt。蓝牙功能电源开关也已通过，但这不等同 BlueZ 可用。
- 修复 OSAL 停止线程后未清空指针，导致销毁时重复 kthread_stop 的卸载死锁。用户本轮物理重启后，SHA256 191cda432666edeb860106bed95990a4f2e8c56027b229798f33b2b2c7977c2e 的 WMT 模块实际 insmod/rmmod 返回 WMT_UNLOAD_PASS。
- 原生 pro6-bt-hci 已注册 hci0，真实 H4/STP/BTIF 命令收发成功，能读到芯片版本、BR/EDR 和 LE 功能、缓冲大小；地址加载本机保存的原厂 BT_Addr 后是 68:3E:34:9E:C0:62。没有写 NVRAM 分区。
- 蓝牙仍未可用：自动初始化的 LE Set Event Mask (0x2001) 返回 0x20（Unsupported LL Parameter Value），因此 btmgmt 控制器列表为空。单独诊断基础掩码 0x1f 成功，额外 bit5..10 每项均返回 -95。固件功能报告与实际接受范围不一致；未伪造成功响应或绕过验收。
- 依据固定提交 gemian 8cfe6596 的 hci_stp.c/h 和 bt_conf.h 实现工厂校准 setup；随后从本机官方系统镜像只读提取 libbluetooth_mtk.so / libbluetooth_mtk_pure.so，正在核对其初始化指令与固件能力。反汇编和符号表在 evidence/。诊断版本模块仍为手动加载，未设置自动启动。
- Wi-Fi 完整驱动尚未编译完成，剩余主要为 P2P cfg80211 回调的新签名、AHB remove 回调和 proc 写入边界。proc 的 count+1 溢出/末尾越界已在适配脚本修正，下一次构建需验证。Wi-Fi 尚无 PHY/interface，不能扫描或联网。
- 桌面、触控、电池、USB SSH 仍正常。当前证据 evidence/bluetooth-native-v22-current.txt 和 evidence/pro6-hci-init2.txt。关机断电在用户拔 USB 测试已通过；插线后启动仍是现有行为，未实现关机充电界面。

下一步：定位原厂 BLE 初始化/能力差异，验证真实扫描与配对；继续 Wi-Fi P2P/AHB API 适配；检查 WMT 卸载后残留 proc 节点警告，完成无线服务持久性和重启验证。无线问题尚未修复完成。
