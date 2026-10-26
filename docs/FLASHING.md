# 刷机全流程（Meizu PRO 6 → 原生 Ubuntu）

> 目标读者：手上有 PRO 6（Flyme 8.0.5.0A），想刷入本项目的原生 Ubuntu。
> 全程风险自负。**第 1、2 步完成之前不要做任何写操作。**

## 流程总览

```
0. 准备材料与工具
1. 开启 Flyme 系统权限（root）          [Android 侧]
2. 全分区备份                            [Android 侧, 一次性]
3. 构建内核 + 模块 + boot.img            [PC 侧]
4. 部署 Ubuntu rootfs 到 userdata        [手机侧]
5. 写入 boot 分区并校验                  [手机侧]
6. 首次启动与验收
```

---

## 0. 准备材料

| 项 | 说明 |
|---|---|
| PRO 6 (mz6797) | Flyme 8.0.5.0A（本流程基于此版本） |
| 原厂固件 zip | `pro6-flyme-8.0.5.0A-verified.zip`（用于提取 CONSYS/BT 无线固件，**不是**用来刷回） |
| PC 环境 | x86_64 Linux 或 WSL2：`gcc-aarch64-linux-gnu bc bison flex libssl-dev python3-cryptography python3-yaml adb fastboot cpio gzip` |
| 数据线 | USB 2.0 即可 |
| 耐心 | 内核全量构建约 2-4 小时（4 核 PC） |

仓库内不含原厂固件与分区镜像（版权），按 `docs/original/原厂启动链分析` 的校验方法自行从官方渠道获取并核对 SHA256。

## 1. 开启 Flyme 系统权限（root）

1. 手机登录 Flyme 账号，`设置 → 指纹和安全 → 系统权限开放声明`，同意协议并输入账号密码（**需魅族账号实名**）。重启后 `ro.flyme.root.state=1`，`/system/xbin/su` 出现。
2. 关闭锁屏（`屏幕解锁方式: 无锁屏`）——否则 ADB 会话可能拿不到授权弹窗。
3. PC 上 `adb shell`，执行 `su 0 id`：手机弹授权框，勾选"记住选择"并允许，应输出 `uid=0(root)`。
   - 踩坑：Android 尚未启动完成时授权弹窗出不来，务必等桌面就绪。
   - 踩坑：Flyme 的 `su` 会在 stdout 打两行授权日志，读分区做校验时要去掉。

## 2. 全分区备份（不可跳过）

在 `adb shell` + `su 0` 下，用仓库 `scripts/backup-partitions.sh`（见下文"脚本补充"）逐分区 `dd` + `sha1sum`，把 `boot/recovery/lk/lk2/preloader/devinfo/gpt/protect*/nv*/proinfo/para/scp*/md*` 全部拉回 PC。至少必须备份：

```
boot (mmcblk0p25)   recovery (mmcblk0p1)   lk (p23)   lk2 (p24)
gpt                 preloader              proinfo    nvram
```

`scripts/` 内置 `backup-partitions.sh`；产物请离线保存。**有备份才有救砖能力。**

## 3. 构建（PC 侧）

详见 [BUILDING.md](BUILDING.md)。摘要：

```sh
# 3.1 内核（linux-6.18.57 vanilla + 本仓库 kernel/patches/*.py 生成的 MTK 驱动）
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- defconfig   # 用 kernel/mt6797-defconfig
make -j$(nproc) Image.gz

# 3.2 boot 镜像 = Image.gz + DTB，AOSP 头 + 公开测试密钥签名（keys/）
python3 scripts/build_ubuntu_boot_probe.py --kernel Image.gz --dtb xxx.dtb \
    --name ubuntu --target boot --cpus 8 --memory auto --pad-to-partition
```

要点（细节都在注释与原始文档里）：
- PRO 6 的 LK **不校验 boot 外层签名**（见 `docs/original/自主移植进展.md` 的 Unicorn 模拟分析），但镜像格式必须保持 Android boot header + 页对齐 + 可选 PKCS#7 尾巴，LK 才会解析。
- `bootopt=64S3,32N2,64N2` 必须保留；LK 会截断超长的 cmdline，所以关键参数要放在短拷贝边界内。
- rootfs 放在 **userdata 分区的 `/pro6-ubuntu` 目录**，用 initramfs `switch_root` 进入；这样 Android 的 recovery 可保留作救援通道。

## 4. 部署 rootfs（手机侧）

rootfs 用官方 Ubuntu base 镜像（aarch64）解包到 `/data/pro6-ubuntu`，然后 `scripts/configure-ubuntu-system.sh` 完成：

- USB RNDIS 网络 + SSH（`pro6-usb.service` / `pro6-sshd.service`）
- 主机名、apt 源（初期可走 PC SOCKS 代理 `socks5h://127.0.0.1:1080`）
- 禁用与手机场景冲突的 systemd 单元（ssh.socket 等）
- 安装 `rootfs/pro6-console/`（kiosk 控制台）与 `rootfs/systemd-units/`

**镜像来源（重要）**：从 PC 把 `ubuntu-base` tarball 经 `adb push` 到手机 `/data/` 解包；Ubuntu 官方 cdimage 下载后核对 SHA256。

## 5. 写入 boot 并校验

仓库 `scripts/install-ubuntu-default-boot.sh`（来自实机验证）的逻辑：

```sh
test "$(cat /sys/class/block/mmcblk0p25/size)" = 32768   # 16MB
grep -qx PARTNAME=boot /sys/class/block/mmcblk0p25/uevent
sha1sum /dev/mmcblk0p25                       # 必须等于备份时的原厂值
sha256sum ubuntu-xxx.img                      # 必须等于构建输出
dd if=ubuntu-xxx.img of=/dev/mmcblk0p25 bs=1048576 conv=fsync
sha256sum /dev/mmcblk0p25                     # 写入后回读必须一致
```

**三重校验全过才允许重启。** 若回读不一致，立即重新 dd 备份镜像。

## 6. 首次启动

- 重启。约 40 秒内进入 Ubuntu；USB 枚举出 RNDIS 网卡，PC 侧 `ssh root@192.168.76.1`（密码 `rootqpzmA!`，首次登录后请改）。
- 验收清单：`uname -a`（6.18.57）/ `systemctl`（PID 1）/ `free -h`（~3.6GB）/ `ip link`（wlan0 或 usb0）。
- 显示/触控/电池/GPU 依赖 `rootfs/systemd-units/` 里的服务与 `kernel/modules/` 的 `.ko`，按 `docs/PORTING-NOTES.md` 逐项检查。

## 救砖

- recovery 分区保留可引导镜像时：`fastboot flash recovery 救援镜像` 后从 recovery 进 Ubuntu 实验环境，修复 boot。
- boot 彻底写坏：用第 2 步的备份 `fastboot flash boot boot.img`（需 fastboot 模式可用；PRO 6 的 LK 支持 `fastboot flash recovery`，实测记录在 `docs/original/`）。
- 完全黑砖：MTK 平台可用 mtkclient 从 BROM 模式重写分区（本项目未深度使用，仅作最后手段参考）。

## 已知限制

- 快充协议（mCharge）未移植，充电约 5V/1.5A 上限
- 音频、相机、蜂窝网络未移植
- A72 双核默认离线（`maxcpus=8`），打开会引入二级缓存集群电源问题
- eMMC 以保守 25MHz 时钟运行
