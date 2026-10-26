# Meizu PRO 6 (MT6797) — Native Ubuntu Port

[English](#english) | [中文](#中文)

<a name="english"></a>
## What is this

A complete, working port of **Ubuntu 26.04 LTS (aarch64, real systemd PID 1) with mainline Linux 6.18.57** to the Meizu PRO 6 smartphone (MT6797 / Helio X20, 2016). The phone boots straight into Ubuntu from eMMC, with a phone UI (Phosh), working touchscreen, battery gauge, USB networking, SSH, GPU acceleration (Mali-T880 via Panfrost), Wi-Fi and an AI agent stack (Hermes Agent) running as services.

Everything here was reverse-engineered and hand-ported from scratch: no existing PRO 6 Linux port existed when this started. The original research notes (in Chinese) are preserved under [`docs/original/`](docs/original/).

**Status highlights**

| Component | Status |
|---|---|
| Boot chain (LK → custom boot.img) | ✅ working, verifiable install with read-back |
| Kernel 6.18.57 (mainline) | ✅ built, source patches included |
| Display / touchscreen (DSI + Synaptics RMI4) | ✅ Phosh desktop, 1080×1920 |
| GPU Mali-T880 (Panfrost, glmark2 verified) | ✅ incl. custom power-on sequence |
| Battery gauge (BQ27532), PMIC (MT6351) | ✅ native drivers |
| Wi-Fi (MT6797 CONSYS, vendor firmware) | ✅ |
| Bluetooth | ⚠️ HCI up, LE init issues remain |
| Audio / camera / modem | ❌ not ported |
| mBack home key | ✅ kernel module + console integration |

> ⚠️ **This port is for the Meizu PRO 6 (mz6797, M570Q/H) only.** Do not flash any image from this project on other MT6797 devices (Meizu PRO 6s/Plus, MX6 differ; PRO 5 is Exynos).

---

<a name="中文"></a>
## 项目简介

魅族 PRO 6（MT6797 / Helio X20）的**原生 Ubuntu 移植**：手机从 eMMC 直接引导 Ubuntu 26.04 LTS + 主线内核 6.18.57，Phosh 手机桌面、触控、电量计、GPU 加速（Panfrost）、Wi-Fi、SSH 全部可用，Hermes AI 助理作为系统服务常驻。

全部驱动与启动链均为自主逆向移植，原始研究笔记在 [`docs/original/`](docs/original/)。

**风险提示**：刷写 boot 分区会使手机失去原厂 Android（备份恢复除外）。所有操作风险自负，请先完成全分区备份。

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/FLASHING.md](docs/FLASHING.md) | **完整刷机流程**（root → 备份 → 构建 boot → 写入 → 引导 Ubuntu） |
| [docs/BUILDING.md](docs/BUILDING.md) | 内核交叉编译、外置模块构建、boot 镜像打包 |
| [docs/PORTING-NOTES.md](docs/PORTING-NOTES.md) | 各硬件移植要点与踩坑记录（GPU/PMIC/无线/触控） |
| [docs/original/](docs/original/) | 原始研究笔记（启动链分析、签名验证、逐步进展） |

## 仓库结构

```
pro6-ubuntu/
├── docs/              # 刷机流程、构建说明、移植笔记、原始研究
├── scripts/           # boot 镜像打包、ramdisk 构建、系统配置、安装脚本
├── kernel/
│   ├── mt6797-defconfig   # 内核配置（6.18.57 实测可用）
│   ├── dts-overlays/      # GPU/mBack/I2C7 设备树 overlay
│   ├── patches/           # 6.18 API 适配补丁脚本（wifi/wmt/btif/consys）
│   └── modules/           # 自制外置驱动源码（电池/GPU/mBack/收音机/蓝牙/无线）
├── rootfs/
│   ├── pro6-console/      # GTK kiosk 控制台（监控/终端/WiFi 页 + AI 入口）
│   └── systemd-units/     # GPU 上电、按键监听等服务单元
├── keys/                  # AOSP 公开 verity 测试密钥（公开材料，用于签名格式）
└── evidence-ref/          # 证据文件索引（原文档引用的输出样例）
```

## 快速开始（已 root + 已备份的用户）

```sh
# 1. 构建内核（在 x86_64 Linux/WSL2 上）
#    见 docs/BUILDING.md
# 2. 打包 boot.img
python3 scripts/build_ubuntu_boot_probe.py --kernel Image.gz --dtb mt6797-pro6.dtb \
    --name my-ubuntu --target boot --cpus 8 --memory auto --pad-to-partition
# 3. 写入（手机上以 root 执行；分区号与校验见 docs/FLASHING.md）
dd if=ubuntu-my-ubuntu.img of=/dev/block/mmcblk0p25 bs=1048576 conv=fsync
```

完整步骤、依赖下载和救砖说明见 [docs/FLASHING.md](docs/FLASHING.md)。

## License

- 本仓库自有代码（scripts/kernel/rootfs/docs）：MIT
- [`keys/`](keys/) 内的 AOSP verity 测试密钥：Android Open Source Project 公开材料
- 第三方参考：gemini-pda-mainline (ixoo) 提供了 MT6797 启动参考，固定 commit `598040b`
