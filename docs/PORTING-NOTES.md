# 移植要点与踩坑记录

按子系统整理的硬核经验，原始分析在 `docs/original/`。每条都是实机验证过的结论。

## 启动链

- LK（Meizu 版）正常 boot 路径的签名校验是**空实现**：反汇编发现校验函数 `movs r0,#0; bx lr` 直接返回成功，Unicorn 模拟证实传入无效指针也不触发读取。`green` verifiedbootstate 不可作为"签名已验证"的证据。但 recovery 分区似乎另有路径，别赌。
- LK 从 Android boot header 拼内核 cmdline 时**短拷贝**：超长参数被截断。把 `bootopt=64S3,32N2,64N2` 和关键参数放前面。
- `fastboot flash recovery <img>` 在 LK 里可用（实测 `OKAY`）；boot 分区写入走手机端 dd + 回读校验更稳。
- Flyme su 的 stdout 有两行授权日志，脚本读分区时要剥掉。

## 电源 (MT6351 PMIC + SPM)

- MT6797 的 SPM 寄存器表有两套文档（老 MT6755 模板 `0x214` vs 真实 `0x334/0x338/0x33c/0x340-34c`）。**写 0x210-0x214（CA15 CPU 域）会 watchdog 重启**。
- 域状态要查双寄存器：PWR_STATUS(0x180) 和 PWR_STATUS_2ND(0x184) 都置位才算上电。
- MFG 家族（GPU）：`MFG_ASYNC(0x334,bit13) → MFG(0x338,bit12) → CORE0-3(0x340-34c,bit8-11)`，SRAM 控制在独立寄存器 0x33C（PDN bits0-1，ACK bits16-17，CORE 的 ACK 在 bits20-23）。
- **GPU 上不了电的根因是外部供电**：FAN53555 buck 在 I2C7 总线 0x60 地址（不是设备树写的 rt5735@0x1c），LK 留 EN=0。reg0 bit7 置 1 → MFG 立即 ack。
- vendor 完整 GPU 上电序列里我们只需要：buck 使能 + RG_GPULDO(infracfg_ao+0xfbc=0x1ff) + MTCMOS。vendor 的 toprgu 复位脉冲和总线保护反而会把 GPU 内部电源 FSM 打乱。
- MTCMOS 上电会把 CORE0-3 复位，父域上电后要重新上核。
- probe 时打 "shader/tiler power transition timeout" 是良性的，绑定照常成功。

## 无线 (CONSYS)

- Wi-Fi/蓝牙固件从官方 Flyme zip 只读提取（`system/etc/firmware/`），MD5/SHA256 全程校验。
- WMT 卸载死锁：OSAL 停线程后未清空指针 → 二次 kthread_stop。修复见 `kernel/modules/mt6797-wmt-port/`。
- BT HCI 能到 H4/STP/BTIF 命令收发、读芯片版本，但 LE Set Event Mask 返回 Unsupported——固件能力与实际接受范围不一致，未解决。

## 显示 / 触控

- 起步阶段用 `simpledrm`（LK 初始化的 framebuffer 直接继承）+ 用户态刷新守护进程，最快拿到画面。
- 触控 Synaptics S3718AR 走主线 `rmi4_i2c`，挂在 I2C1 (0x11011000) @0x20。
- DSI 命令模式面板由 LK 点亮，主线内核接管显示控制器前**不要碰 DCS 0x28/0x29**（面板会永久黑掉）。

## 电池

- BQ27532 只读驱动（不改充电参数/校准），power_supply 类设备 + UPower 集成。
- 充电慢的真相：USB 500mA 输入 − 系统消耗 = 50-70mA 进电池。mCharge 高压快充需要 MTK 专有充电协议，主线内核没有。
- MT6351 BBPU 关机路径接入后才能真关机（拔线不复活）。

## 实用工具

- 屏幕截图：`/dev/mem` 直读 fb（地址从 dmesg `simple-framebuffer` 行取），BMP 打包后 ImageMagick `-rotate 180`。
- Wayland 截图：weston 14 kiosk 下 grim/weston-screenshooter 不可用（协议未开放），fb 直读最可靠。
- GPU 负载测试：EGL surfaceless + pbuffer 离屏渲染（`gpuload.py` 思路），glmark2-es2-wayland 跑分需窗口环境。
- GPU 使用率采样：`/sys/devices/platform/13040000.mali/power/runtime_active_time` 差分（panfrost 不导出 fdinfo 引擎统计）。

## 服务组织（rootfs/systemd-units/）

- GPU 上电模块必须在 udev 冷插拔之后加载（i2c 适配器要就位），`After=systemd-udev-trigger.service`
- mt6351-radio 若被 udev 提前加载，service 里用 `modprobe`（幂等）而不是 `insmod`
- kiosk 控制台窗口几何**不能超过屏幕**（1080x1920），否则 kiosk-shell 以协议错误杀客户端——内容超高必须放 ScrolledWindow
