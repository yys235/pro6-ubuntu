# 构建说明（内核 / 模块 / boot 镜像）

## 环境

- x86_64 Linux 或 WSL2（本项目在 WSL2 Ubuntu 上构建）
- 依赖：`gcc-aarch64-linux-gnu build-essential bc bison flex libssl-dev libelf-dev cpio python3 python3-cryptography python3-yaml`
- 源码：https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.18.57.tar.xz

## 1. 内核

```sh
tar -xf linux-6.18.57.tar.xz && cd linux-6.18.57
# 基础配置（含 MT6797 平台、panfrost、MTK SPM/时钟、RMI4 触控等）
cp ../pro6-ubuntu/kernel/mt6797-defconfig .config
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make -j$(nproc) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image.gz
# 输出: arch/arm64/boot/Image.gz (~14MB)
```

`kernel/patches/` 里的脚本用于把 **MTK 厂商无线驱动**（wifi/wmt/btif/consys，源自 gemini-pda-mainline 固定 commit `598040b`）适配到 6.18 API。它们按文件改写驱动源码并调用 kbuild：

```sh
python3 ../pro6-ubuntu/kernel/patches/adapt-wifi-6.18.py   # 逐个执行，见脚本头部注释
```

无线驱动源码树：`kernel/modules/mt6797-{wifi,wmt,btif}-port/`、`pro6-consys-readonly/`（本仓库已收录改后版本；原版从 gemini 仓库取）。

## 2. 外置内核模块

全部自制驱动在 `kernel/modules/`，每个目录有独立 Makefile，构建方式一致：

```sh
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -C <kernel-build-dir> M=$PWD modules
```

| 模块 | 作用 |
|---|---|
| pro6-bq27532-driver | 电池电量计（只读，PowerSupply/UPower） |
| pro6-gpu | GPU 上电（FAN53555 buck + SRAM LDO + MFG MTCMOS）+ mali 设备树 overlay 注入 |
| pro6-homekey / pro6-mback | mBack 实体键（PMIC homekey IRQ） |
| pro6-i2c7 | GPU PM 总线（I2C7）启用 overlay |
| pro6-radio-regulator | MT6351 无线电源轨（VCN18/28/33 + VGPU） |
| pro6-bt-hci | 蓝牙 HCI（H4/STP/BTIF） |
| mt6797-wifi/wmt/btif-port | 无线平台驱动（CONSYS 上下电、WMT 协议） |

GPU 的完整上电配方在 `kernel/modules/pro6-gpu/pro6-gpu.c` 注释里——LK 交付时 GPU 供电 buck（I2C7@0x60 FAN53555）是关的，不开它整个 GPU 总线死锁，这是移植的最大坑之一。

## 3. boot.img 打包

`scripts/build_ubuntu_boot_probe.py`：以原厂 recovery 镜像为模板（保页大小 2048、头部布局），替换 kernel+DTB 与 ramdisk，用 `keys/` 里 AOSP 公开 verity 测试密钥做 PKCS#1.5 签名尾巴（LK 在该机不校验，但保持格式一致）。

```sh
python3 scripts/build_ubuntu_boot_probe.py \
    --kernel Image.gz --dtb mt6797-pro6.dtb \
    --name ubuntu --target boot --cpus 8 --memory auto \
    --pad-to-partition
# 产物: ubuntu-ubuntu.img (16MB)
```

- DTB：从原厂 boot.img 提取的 DTB 反编译 → 打补丁（见 kernel/dts-overlays/ 的改动点）→ 重编译
- ramdisk：`scripts/build_ubuntu_early_ramdisk.py` 生成最小 initramfs（mount userdata、switch_root 到 /pro6-ubuntu、内置 USB 网络助手）
- **cmdline 长度**：LK 只短拷贝头部 cmdline，`bootopt` 必须在位（FLASHING.md 踩坑节）

## 4. 部署到手机

见 FLASHING.md 第 4-5 步；`scripts/install-ubuntu-default-boot.sh` 是实机验证过的写入+三重校验脚本模板。
