# 魅族 Pro 6 安装 Linux：初步可行性研究

研究日期：2026-10-18。范围为标准 Pro 6；Pro 6s、Pro 6 Plus 必须另行识别。本文为早期调查记录；后续已通过 ADB 只读识别实机、分析固件和重建 recovery。请优先阅读《研究结论.md》及详细实机/签名记录；以下不是已验证刷机教程。

## 结论

目前未找到可直接使用的 Pro 6 Ubuntu Touch / postmarketOS 成套移植。原生启动 Linux 应视为新移植项目，首要门槛是本机备份、救援及自定义 boot 启动能力，其次是匹配的内核源码与驱动。未搜到不能证明不存在。

若目的是运行 SSH、Python、Linux 服务，可以先评估原 Flyme 下的 chroot / proot；若要求替换 Android，则必须继续攻克启动链和硬件适配。chroot / proot 共享 Android 内核，不等同于原生 Linux 刷机；旧系统的应用和运行时兼容性也需实测。

## 已核实的公开证据

1. 魅族官方规格：Pro 6 使用 Helio X25、Mali-T880、4GB 内存、32/64GB 存储。这不构成 Linux 驱动支持证据。
   https://m.meizu.com/in/products/pro6/spec.html
2. UBports 设备目录列有 Pro 5、MX4，本轮未找到 Pro 6 条目。不能刷 Pro 5 镜像到 Pro 6。
   https://devices.ubuntu-touch.io/
3. Pro 5 的 postmarketOS 页面明确是 Exynos 7420 平台，不能移用到 Helio X25。
   https://wiki.postmarketos.org/wiki/Meizu_Pro_5_(meizu-turbo)
4. mtkclient 的 brom_config.py 有 MT6797/MT6767 配置，描述包含 Helio X23/X25/X27，使用 mt6797_payload.bin。它是芯片级研究入口，不能推导本机读写、解锁或救砖必然成功。
   https://github.com/bkerler/mtkclient/blob/main/mtkclient/config/brom_config.py
5. 本轮通过 GitHub API 枚举 meizuosc 公开仓库，看到 Pro 5 的 m576 和 MX6 的 m685，未看到明确标为 Pro 6 的仓库。MX6 源码可以分析平台共性，不能当 Pro 6 匹配内核或直接刷入。
   https://github.com/meizuosc
   https://github.com/meizuosc/m685

## 与 L36h 项目的关系

已阅读 ../L36H 刷UT-GPT/publication/STATUS.md 和 GUIDE.zh-CN.md。

L36h 是 yuga / APQ8064 / ARMv7，已有 UT20.04.6 ARMHF 桌面、触控和网络实机证据；同时仍有长期稳定性及发布复现缺口。Pro 6 无法继承这些硬件支持结论。

可以复用的经验：
- 先保留原厂启动镜像、分区表、设备独有校准数据和恢复入口，再做实验。
- 按标签和实际分区容量识别布局，镜像传输后核对字节数、SHA256及回读。
- 首先打通独立救援通道，再逐步验证 USB 网络、SSH、Wi-Fi、显示、触控与电源。
- 关屏能运行不等于无 USB 供电或跨日稳定；出现 panic 要保留日志，不能靠短测判断已修复。

不可复用：L36h boot、ARMHF 根系统、Android 硬件容器、分区编号、Sony 解锁流程、LM3533 背光设置及 Qualcomm WLAN/蓝牙初始化。Pro 6 的用户空间位宽也应以实机 ABI 和内核能力决定，不能只看 CPU 支持 64 位。

## 路线比较

| 路线 | 要解决的问题 | 本轮判断 |
|---|---|---|
| Flyme + proot | 兼容该 Android 版本的程序、发行版用户空间与内核系统调用 | 可先评估，保留 Android，性能和后台限制需实测 |
| Flyme + root + chroot | 本机 root、挂载、权限、后台与网络 | 适合先探索服务器用途，root 不代表 bootloader 已解锁 |
| 原厂内核 + Linux initramfs/rootfs | boot 签名/校验、自定义启动、内核配置、USB gadget、存储和网络 | 原生研究第一候选，尚未证明可行 |
| Ubuntu Touch | 上述条件，再加匹配硬件适配层、图形栈及 Android 容器 | 暂无可直接刷的已核实方案，通用 rootfs 不能替代移植 |
| 主线 Linux / postmarketOS | SoC及板级设备树、显示、电源、存储、网络等驱动 | 长期移植方向，暂不能承诺可用桌面 |

## 推进顺序与通过条件

### 1. 只读识别

记录机身型号、Flyme 版本、Android 版本、设备代号、ABI、内核版本、root 状态及分区标签。只对选定的 Pro 6 执行，不默认所有 adb 设备都是目标手机。

```text
adb devices -l
adb -s YOUR_SERIAL shell getprop ro.product.model
adb -s YOUR_SERIAL shell getprop ro.product.device
adb -s YOUR_SERIAL shell getprop ro.board.platform
adb -s YOUR_SERIAL shell getprop ro.build.display.id
adb -s YOUR_SERIAL shell getprop ro.build.version.release
adb -s YOUR_SERIAL shell getprop ro.product.cpu.abilist
adb -s YOUR_SERIAL shell uname -a
adb -s YOUR_SERIAL shell cat /proc/partitions
adb -s YOUR_SERIAL shell ls -l /dev/block/platform
```

权限拒绝或目录不存在本身也是结果，不为采集信息自动 root、重启或解锁。后续已在 C:/Users/MSIK/AppData/Local/Android/Sdk/platform-tools 找到 adb.exe 和 fastboot.exe，并实际使用 ADB 进行只读调查。

### 2. 备份与恢复

取得匹配本机型号和版本的原厂包；检查包中是否真的包含 boot/recovery/底层恢复必需材料。普通 OTA 包不自动等于完整救砖包。

在确认读取方式后，备份实际 GPT、boot/recovery、启动链及本机独有身份/校准分区；具体名称由分区表确定。备份应有哈希和独立副本。不要为验证备份而盲目回写，也不要用他机校准分区替换。

### 3. 启动链验证

核实当前 Flyme 下 fastboot、preloader、BROM 的实际入口、鉴权与可恢复能力。mtkclient 只作为候选工具，先确认版本、参数和本机兼容性。

必须区分：能进入 fastboot、能读取闪存、能写 boot、能通过签名校验启动自定义镜像。这是四个不同条件。不能以通用解锁命令或其他魅族机型的 secro/preloader 代替实机证据。

### 4. 最小原生启动

启动链允许后，优先分析原厂 boot 的头部、附加校验、内核、DTB和 ramdisk。第一里程碑是最小 initramfs 启动并获得 USB 网络/串口日志或 shell；是否可用临时启动方式须以本机 bootloader 支持为准。

再按 USB/SSH → 内部存储 → Wi-Fi → 显示/触控 → 关屏、电源和温控推进。即使原厂内核可复用，也需检查其对目标 rootfs 的系统调用、命名空间、cgroup 等支持；没有完整源码时扩展能力会受限。

### 5. 服务或桌面验收

服务器：冷启动、断网重连、关屏、拔 USB、温控、持续充电和跨日负载。桌面：另外验证图形加速、触控、输入法、音频和休眠唤醒。相机、指纹、蜂窝不能在未测试时宣称可用。

## 当前缺口

- 本机准确型号、固件版本、ABI及 root/启动链状态。
- 可验证的 Pro 6 自定义启动成功记录。
- 匹配 Pro 6 的可构建完整内核源码与配置。
- 本机完整备份、可确认恢复路径及原厂镜像。

下一步最有价值的工作是采集本机只读信息，据此选择服务环境路线，或继续进行原生启动研究。当前不具备生成可靠刷机命令的证据。
