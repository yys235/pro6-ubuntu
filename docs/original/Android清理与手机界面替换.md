# Android 清理与触摸界面替换

2026-10-18。本次用户明确要求清除 Android 并更换难用的 Xfce 桌面。

已完成：
- 原 userdata 中除 pro6-ubuntu 与 lost+found 外的目录均已清理。
- 校验 GPT 标签与大小、确认未挂载后，discard custom(p3)、system(p30)、cache(p31)，首中尾抽样均为空白。
- 保留 boot/recovery 中的 Ubuntu，以及 LK、TEE、基带、NVRAM/校准等启动硬件必需固件。
- 改为原生 Linux USB RNDIS + DHCP，Windows 10 内置驱动自动识别；手机192.168.76.1、电脑192.168.76.2。
- 原生 USB 已通过正常重启验证；已移除手机 /usr/sbin/adbd、/adb_keys、/system 和旧USB调试helper，重启后无adbd进程。
- Connect-Ubuntu.ps1 已改为直接SSH，无需ADB。
- Linux 6.18.57 #8，DRM/simpledrm 内建，/dev/dri/card0 与 fb0 均已实机验证。
- 当前boot镜像ubuntu-phosh-drm-v13.img SHA256：7e9ebdb2f152a78bf362800b8bf970ab1694bd51810482ccb767dee080012ce7。
- Phosh0.54、Phoc0.54、Stevia0.53 已从Ubuntu官方APT安装。

后续实机进展（2026-10-19）：
- Phosh 已正常启动并通过多次启动，文件管理器手机布局正常。
- 360x640逻辑尺寸、软件渲染、自动键盘和无密码锁屏已配置。
- 键盘自动尺寸问题已修复，用户确认输入正常。
- 当前内核/镜像、电池和关机验证见根目录 Ubuntu移植进展.md 与 evidence/基础功能测试结果.md；上文 #8/v13 为历史阶段记录。
- Wi-Fi、蓝牙等基础硬件仍在适配，不得宣称完整移植完成。

USB曾发生ADB传输阻塞；重连后恢复，确认并非eMMC discard卡死。原生USB网络切换后继续工作。
