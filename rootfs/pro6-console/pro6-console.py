#!/usr/bin/env python3
"""PRO6 ops console: network/system monitor, Wi-Fi configuration, shell.

Runs as a kiosk app under Weston. Three pages switch from the header bar.
An on-screen keyboard drives the VTE terminal and text entries (the phone
has no physical keyboard).
"""
import collections
import gi
import os
import subprocess
import threading
import time

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, Vte, GLib, Pango

MON_INTERVAL = 2000  # ms
AUTO_REFRESH = 10  # seconds between auto refreshes of the monitor page
CHART_SAMPLES = 120  # 1 Hz history kept by each sparkline


def sh(args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


PRO6_CSS = """
button { padding: 14px 18px; }
entry { min-height: 46px; }
headerbar { min-height: 60px; }
headerbar button { padding: 12px 20px; }
"""

def apply_css():
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-font-name", "WenQuanYi Zen Hei 36")


class Sparkline(Gtk.DrawingArea):
    """1 Hz line chart, fixed 0-100 scale, CHART_SAMPLES points wide."""

    def __init__(self, title, color):
        super().__init__()
        self.title = title
        self.color = color
        self.data = collections.deque(maxlen=CHART_SAMPLES)
        self.set_size_request(-1, 150)
        self.connect("draw", self.on_draw)

    def push(self, v):
        self.data.append(max(0.0, min(100.0, v)))
        self.queue_draw()

    def on_draw(self, _w, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        cr.set_source_rgb(0.13, 0.13, 0.16)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgb(0.35, 0.35, 0.40)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()
        # 25/50/75% gridlines
        cr.set_source_rgb(0.22, 0.22, 0.26)
        for frac in (0.25, 0.50, 0.75):
            y = h - 8 - (h - 40) * frac
            cr.move_to(4, y)
            cr.line_to(w - 4, y)
        cr.stroke()
        cr.select_font_face("sans-serif")
        cr.set_font_size(18)
        cr.set_source_rgb(0.92, 0.92, 0.92)
        cur = self.data[-1] if self.data else 0.0
        cr.move_to(8, 24)
        cr.show_text(f"{self.title}  {cur:.0f}%")
        n = len(self.data)
        if n < 2:
            return False
        top, bot = 34, h - 8
        x0, x1 = 4, w - 4
        cr.set_source_rgb(*self.color)
        cr.set_line_width(2)
        for i, v in enumerate(self.data):
            x = x0 + (x1 - x0) * i / (CHART_SAMPLES - 1)
            y = bot - (bot - top) * v / 100.0
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
        cr.set_source_rgb(0.6, 0.6, 0.65)
        cr.set_font_size(13)
        cr.move_to(w - 60, top + 14)
        cr.show_text(f"max {max(self.data):.0f}")
        cr.move_to(w - 60, bot - 2)
        cr.show_text(f"min {min(self.data):.0f}")
        return False


class MonitorPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        # content lives in a scrolled inner box so the stacked charts can
        # exceed the screen height without the window growing past it
        # (kiosk shell kills clients whose geometry exceeds the output)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(inner)
        self.pack_start(scroll, True, True, 0)
        self.rows = {}
        grid = Gtk.Grid(column_spacing=16, row_spacing=6, margin=12)
        labels = [
            ("load", "负载"),
            ("mem", "内存"),
            ("battery", "电池"),
            ("temp", "温度"),
            ("uptime", "运行"),
            ("route", "默认路由"),
            ("inet", "互联网"),
        ]
        for i, (key, name) in enumerate(labels):
            k = Gtk.Label(xalign=0)
            k.set_markup(f"<b>{name}</b>")
            v = Gtk.Label(xalign=0)
            v.set_line_wrap(True)
            grid.attach(k, 0, i, 1, 1)
            grid.attach(v, 1, i, 1, 1)
            self.rows[key] = v
        inner.pack_start(grid, False, False, 0)

        # 机器配置说明: static facts about this device
        machine = Gtk.Frame(label="机器配置", margin=12)
        mgrid = Gtk.Grid(column_spacing=16, row_spacing=4, margin=10)
        mrows = []
        for i, (k, v) in enumerate(self._machine_info()):
            kl = Gtk.Label(xalign=0)
            kl.set_markup(f"<b>{k}</b>")
            vl = Gtk.Label(xalign=0, hexpand=True)
            vl.set_text(v)
            mgrid.attach(kl, 0, i, 1, 1)
            mgrid.attach(vl, 1, i, 1, 1)
            mrows.append(vl)
        machine.add(mgrid)
        inner.pack_start(machine, False, False, 0)

        charts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin=8)
        self.chart_cpu = Sparkline("CPU", (0.30, 0.75, 1.00))
        self.chart_mem = Sparkline("内存", (0.40, 0.90, 0.45))
        self.chart_disk = Sparkline("磁盘", (1.00, 0.65, 0.30))
        self.chart_gpu = Sparkline("GPU", (0.85, 0.40, 0.90))
        for c in (self.chart_cpu, self.chart_gpu, self.chart_mem,
                  self.chart_disk):
            c.set_size_request(-1, 110)
            charts.pack_start(c, True, True, 0)
        inner.pack_start(charts, False, False, 0)

        self._cpu_prev = None
        self._gpu_prev = None
        self._disk_total = self._disk_used = 0
        self._disk_probe()
        GLib.timeout_add(1000, self._sample)

        self.netframe = Gtk.Frame(label="网络接口", margin=12)
        self.netgrid = Gtk.Grid(column_spacing=16, row_spacing=4, margin=10)
        self.netframe.add(self.netgrid)
        inner.pack_start(self.netframe, False, False, 0)

        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                         margin=8)
        self.refresh_btn = Gtk.Button(label="手动刷新")
        self.refresh_btn.connect("clicked", self.on_manual_refresh)
        self.count_lbl = Gtk.Label(label=f"自动刷新: {AUTO_REFRESH}s")
        self.reboot_btn = Gtk.Button(label="重启")
        self.reboot_btn.connect("clicked", self.on_reboot)
        self.power_btn = Gtk.Button(label="关机")
        self.power_btn.connect("clicked", self.on_poweroff)
        for w in (self.refresh_btn, self.count_lbl, self.reboot_btn,
                  self.power_btn):
            btnrow.pack_start(w, True, True, 0)
        inner.pack_start(btnrow, False, False, 0)
        self._next_refresh = time.monotonic() + AUTO_REFRESH
        self._confirm = None

        self._inet_state = "检测中"
        threading.Thread(target=self._inet_loop, daemon=True).start()

    def _inet_loop(self):
        while True:
            rc, out, _ = sh(
                ["curl", "-s", "-m", "8", "-o", "/dev/null",
                 "-w", "%{http_code} %{time_total}s",
                 "http://connectivitycheck.gstatic.com/generate_204"])
            state = "在线 " + out if rc == 0 and out.split(" ")[0] == "204" else "离线"
            GLib.idle_add(self._set_inet, state)
            threading.Event().wait(15)

    def _set_inet(self, state):
        self._inet_state = state
        self.rows["inet"].set_text(state)
        return False

    def _disk_probe(self):
        try:
            st = os.statvfs("/")
            self._disk_total = st.f_blocks * st.f_frsize
            self._disk_used = (st.f_blocks - st.f_bfree) * st.f_frsize
        except OSError:
            pass

    def _machine_info(self):
        # CPU: cluster makeup from per-cpu "CPU part" values
        parts = {}
        try:
            for line in read("/proc/cpuinfo").splitlines():
                if line.startswith("CPU part"):
                    p = line.split(":")[1].strip()
                    parts[p] = parts.get(p, 0) + 1
        except OSError:
            pass
        names = {"0xd03": "A53", "0xd07": "A57", "0xd08": "A72", "0xd09": "A73"}
        cpu_desc = " + ".join(
            f"{c}×{names.get(p, p)}" for p, c in sorted(parts.items(), reverse=True))
        cpu_desc = f"{os.cpu_count() or 0} 核 ({cpu_desc})" if parts else "未知"
        # RAM / disk
        try:
            mt = int([l for l in open("/proc/meminfo")
                      if l.startswith("MemTotal")][0].split()[1]) // 1024 // 1024
        except (OSError, IndexError, ValueError):
            mt = 0
        self._disk_probe()
        disk = (f"{self._disk_total // (1 << 30)} GB"
                if self._disk_total else "未知")
        # GPU presence via panfrost render node
        gpu = ("Mali-T880 MC4 · Panfrost"
               if os.path.exists("/dev/dri/renderD128") else "未启用")
        os_name = "Ubuntu 26.04"
        try:
            for line in open("/etc/os-release"):
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return [
            ("型号", "魅族 PRO6 (MT6797 Helio X20)"),
            ("CPU", cpu_desc),
            ("内存", f"{mt} GB"),
            ("磁盘", disk),
            ("GPU", gpu),
            ("系统", f"{os_name} · kernel {os.uname().release}"),
        ]

    def _gpu_active_ms(self):
        # panfrost runtime PM cumulative active time (ms) — the GPU is
        # powered only while jobs run, so deltas give utilization
        try:
            with open("/sys/devices/platform/13040000.mali/power/"
                      "runtime_active_time") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _sample(self):
        # CPU % from /proc/stat deltas
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
            idle = parts[3] + parts[4]
            total = sum(parts)
            if self._cpu_prev:
                dt = total - self._cpu_prev[0]
                di = idle - self._cpu_prev[1]
                pct = 100.0 * (dt - di) / dt if dt > 0 else 0.0
            else:
                pct = 0.0
            self._cpu_prev = (total, idle)
        except (OSError, ValueError):
            pct = 0.0
        self.chart_cpu.push(pct)
        # memory %
        mt = mu = 0
        for line in read("/proc/meminfo").splitlines():
            if line.startswith("MemTotal:"):
                mt = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mu = mt - int(line.split()[1])
        self.chart_mem.push(100.0 * mu / mt if mt else 0.0)
        # disk usage %
        self._disk_probe()
        self.chart_disk.push(
            100.0 * self._disk_used / self._disk_total
            if self._disk_total else 0.0)
        # GPU % from panfrost runtime PM active-time deltas
        ams = self._gpu_active_ms()
        now = time.monotonic()
        if ams is not None and self._gpu_prev is not None and \
                self._gpu_prev[0] is not None:
            dms = ams - self._gpu_prev[0]
            dt = now - self._gpu_prev[1]
            pct = min(100.0, max(0.0, 100.0 * dms / dt)) if dt > 0 else 0.0
        else:
            pct = 0.0
        self._gpu_prev = (ams, now)
        self.chart_gpu.push(pct)
        return True

    def tick_countdown(self):
        left = self._next_refresh - time.monotonic()
        if left <= 0:
            self.refresh()
            self._next_refresh = time.monotonic() + AUTO_REFRESH
            left = AUTO_REFRESH
        self.count_lbl.set_text(f"自动刷新: {int(left) + 1}s")

    def on_manual_refresh(self, _b):
        self.refresh()
        self._next_refresh = time.monotonic() + AUTO_REFRESH

    def _arm(self, btn, label, action):
        # two-step confirmation so a stray tap cannot reboot/shut down
        if self._confirm == action:
            self._confirm = None
            btn.set_label(label)
            sh(["systemctl", action], timeout=10)
            return
        self._confirm = action
        btn.set_label("再按一次确认")
        def _reset():
            if self._confirm == action:
                self._confirm = None
                btn.set_label(label)
            return False
        GLib.timeout_add_seconds(5, _reset)

    def on_reboot(self, btn):
        self._arm(btn, "重启", "reboot")

    def on_poweroff(self, btn):
        self._arm(btn, "关机", "poweroff")

    def refresh(self):
        load = read("/proc/loadavg")
        self.rows["load"].set_text(load)
        mt = mu = 0
        for line in read("/proc/meminfo").splitlines():
            if line.startswith("MemTotal:"):
                mt = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mu = mt - int(line.split()[1])
        self.rows["mem"].set_text(f"{mu // 1024} / {mt // 1024} MiB")
        cap = read("/sys/class/power_supply/pro6-battery/capacity")
        st = read("/sys/class/power_supply/pro6-battery/status")
        cur = read("/sys/class/power_supply/pro6-battery/current_now")
        volt = read("/sys/class/power_supply/pro6-battery/voltage_now")
        try:
            mw = int(cur) * int(volt) // 10 ** 9  # µA×µV -> mW
            cur = f"{int(cur) / 1e6:+.2f}A"
            if abs(mw) >= 1000:
                cur += f" ({mw / 1000:+.1f}W)"
            else:
                cur += f" ({mw:+d}mW)"
        except ValueError:
            pass
        self.rows["battery"].set_text(f"{cap}% {st} {cur}")
        temps = []
        for z in sorted(os.listdir("/sys/class/thermal")) if os.path.isdir("/sys/class/thermal") else []:
            if z.startswith("thermal_zone"):
                t = read(f"/sys/class/thermal/{z}/temp")
                typ = read(f"/sys/class/thermal/{z}/type")
                if t.isdigit():
                    temps.append(f"{typ} {int(t) / 1000:.1f}°C")
        bt = read("/sys/class/power_supply/pro6-battery/temp")
        if bt.isdigit():
            temps.append(f"电池 {int(bt) / 10:.1f}°C")
        self.rows["temp"].set_text("  ".join(temps) or "-")
        up = float(read("/proc/uptime").split()[0] or 0)
        self.rows["uptime"].set_text(f"{int(up // 3600)}h{int(up % 3600 // 60)}m")
        rc, out, _ = sh(["ip", "route", "show", "default"])
        self.rows["route"].set_text(out or "无")

        # interface table
        while True:
            c = self.netgrid.get_child_at(0, 0)
            if not c:
                break
            self.netgrid.remove(c)
        hdr = ["接口", "状态", "IPv4", "RX", "TX"]
        for col, h in enumerate(hdr):
            l = Gtk.Label(xalign=0)
            l.set_markup(f"<b>{h}</b>")
            self.netgrid.attach(l, col, 0, 1, 1)
        row = 1
        for iface in sorted(os.listdir("/sys/class/net")):
            if iface == "lo":
                continue
            state = read(f"/sys/class/net/{iface}/operstate")
            rc, out, _ = sh(["ip", "-4", "-o", "addr", "show", iface])
            ip = out.split()[3].split("/")[0] if out else "-"
            rx = int(read(f"/sys/class/net/{iface}/statistics/rx_bytes") or 0)
            tx = int(read(f"/sys/class/net/{iface}/statistics/tx_bytes") or 0)
            vals = [iface, state, ip, f"{rx / 1e6:.1f} MB", f"{tx / 1e6:.1f} MB"]
            for col, v in enumerate(vals):
                self.netgrid.attach(Gtk.Label(label=v, xalign=0), col, row, 1, 1)
            row += 1
        self.netgrid.show_all()


class WifiPage(Gtk.Box):
    def __init__(self, app):
        self.app = app
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.status = Gtk.Label(xalign=0)
        self.status.set_markup("<b>Wi-Fi: 未连接</b>")
        self.pack_start(self.status, False, False, 0)

        bar = Gtk.Box(spacing=8)
        self.scan_btn = Gtk.Button(label="扫描")
        self.scan_btn.connect("clicked", self.on_scan)
        bar.pack_start(self.scan_btn, False, False, 0)
        self.disc_btn = Gtk.Button(label="断开")
        self.disc_btn.connect("clicked", self.on_disconnect)
        bar.pack_start(self.disc_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

        sw = Gtk.ScrolledWindow(vexpand=True)
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-activated", self.on_row)
        sw.add(self.listbox)
        self.pack_start(sw, True, True, 0)

        row = Gtk.Box(spacing=8)
        self.ssid_lbl = Gtk.Label(label="密码:", xalign=0)
        self.pass_entry = Gtk.Entry(visibility=True)
        self.pass_entry.connect(
            "button-press-event", lambda *_: self.pass_entry.grab_focus())
        self.pass_entry.set_placeholder_text("选择网络后输入密码")
        self.connect_btn = Gtk.Button(label="连接")
        self.connect_btn.connect("clicked", self.on_connect)
        row.pack_start(self.ssid_lbl, False, False, 0)
        row.pack_start(self.pass_entry, True, True, 0)
        row.pack_start(self.connect_btn, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.selected_ssid = None
        self.selected_open = False
        self.refresh_status()

    def refresh_status(self):
        rc, out, _ = sh(["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION",
                         "device", "show", "wlan0"])
        conn = ""
        if rc == 0:
            for line in out.splitlines():
                if line.startswith("GENERAL.CONNECTION:"):
                    conn = line.split(":", 1)[1].strip()
        if conn:
            self.status.set_markup(f"<b>Wi-Fi: 已连接 {conn}</b>")
        else:
            self.status.set_markup("<b>Wi-Fi: 未连接</b>")
        return False

    def on_scan(self, _btn):
        self.scan_btn.set_sensitive(False)
        self.scan_btn.set_label("扫描中…")

        def work():
            sh(["nmcli", "device", "wifi", "rescan"])
            # rescan is async: poll the list until it fills in (or timeout)
            out = ""
            for _ in range(12):
                threading.Event().wait(2)
                rc, out, _ = sh(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                                 "device", "wifi", "list", "--rescan", "no"],
                                timeout=25)
                if rc == 0 and len(out.splitlines()) > 3:
                    break
            nets = []
            seen = set()
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) < 3 or not parts[0]:
                    continue
                ssid, sig, sec = parts[0], parts[1], parts[2]
                if ssid in seen:
                    continue
                seen.add(ssid)
                nets.append((ssid, sig, sec))
            GLib.idle_add(self.fill_list, nets)
        threading.Thread(target=work, daemon=True).start()

    def fill_list(self, nets):
        self.scan_btn.set_sensitive(True)
        self.scan_btn.set_label("扫描")
        for r in self.listbox.get_children():
            self.listbox.remove(r)
        for ssid, sig, sec in nets:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(xalign=0)
            lock = "" if sec in ("--", "", "none") else "🔒"
            lbl.set_text(f"{ssid}  {lock}  {sig}/100")
            row.add(lbl)
            row.ssid, row.open = ssid, sec in ("--", "", "none")
            self.listbox.add(row)
        self.listbox.show_all()
        return False

    def on_row(self, _lb, row):
        self.selected_ssid = row.ssid
        self.selected_open = row.open
        self.ssid_lbl.set_text(f"{row.ssid}:")
        self.pass_entry.set_text("")

    def on_connect(self, _btn):
        if not self.selected_ssid:
            self.status.set_text("请先在列表中点选网络")
            return
        ssid = self.selected_ssid
        pw = self.pass_entry.get_text()
        self.connect_btn.set_sensitive(False)

        def work():
            # drop any stale saved profile so the freshly typed password wins
            sh(["nmcli", "connection", "delete", ssid], timeout=10)
            if self.selected_open or not pw:
                args = ["nmcli", "device", "wifi", "connect", ssid, "ifname", "wlan0"]
            else:
                args = ["nmcli", "device", "wifi", "connect", ssid,
                        "password", pw, "ifname", "wlan0"]
            rc, out, err = sh(args, timeout=40)
            GLib.idle_add(self._connect_done, rc, out or err)
        threading.Thread(target=work, daemon=True).start()

    def _connect_done(self, rc, msg):
        self.connect_btn.set_sensitive(True)
        self.refresh_status()
        if rc != 0:
            self.status.set_text(f"连接失败: {msg}")
            self._show_error(self._classify_failure())
        return False

    def _classify_failure(self):
        rc, out, _ = sh(["journalctl", "--since", "-90 sec", "--no-pager",
                         "-o", "short", "-u", "wpa_supplicant",
                         "-u", "NetworkManager"], timeout=10)
        t = out or ""
        if "pre-shared key may be incorrect" in t or "WRONG_KEY" in t \
                or "psk mismatch" in t:
            return "密码错误（4次握手校验失败）"
        if "status_code=16" in t or "status_code=15" in t \
                or "status_code=14" in t:
            return "AP拒绝连接：此前认证失败过多，已被临时拉黑，请稍后再试"
        if "status_code=1 " in t or "status_code=12" in t \
                or "status_code=13" in t:
            return "AP拒绝关联：网络可能已满或安全类型不匹配"
        if "timed out" in t:
            return "握手超时：信号差或AP无响应"
        if "no APs found" in t or "no matching network" in t:
            return "找不到该网络（可能已关闭或超出范围）"
        if "no-secrets" in t:
            return "缺少密码：加密网络请先输入密码"
        return "连接失败，请检查密码与网络状态"

    def _show_error(self, reason):
        self.app.show_error(f"Wi-Fi 连接失败: {self.selected_ssid}\n原因: {reason}")

    def on_disconnect(self, _btn):
        sh(["nmcli", "device", "disconnect", "wlan0"])
        self.refresh_status()


class KeyboardPanel(Gtk.Box):
    ROWS = [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl"),
        list("zxcvbnm"),
    ]
    SYM_ROWS = [
        list("!@#$%^&*()"),
        list("-_=+[]{}\\|"),
        list(';:"\\\',.<>'),
        list("?/~`"),
    ]

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=4)
        self.app = app
        self.shift = False
        self.ctrl = False
        self.keys = {}
        self.specials = {}
        self.sym = False
        self.letter_rows = [Gtk.Box(spacing=3) for _ in self.ROWS]
        for r in self.letter_rows:
            self.pack_start(r, True, True, 0)
        self.build_letters()
        for group in [
            [("Shift", "shift"), ("Ctrl", "ctrl"), ("符号", "sym"),
             ("Tab", "tab"), ("Esc", "esc"), ("↑", "up"), ("↓", "down")],
            [("←", "left"), ("→", "right"), ("|", "|"), ("-", "-"),
             ("_", "_"), ("/", "/"), ("Space", "space"), ("⌫", "bs"),
             ("↵", "enter")],
        ]:
            row = Gtk.Box(spacing=3)
            for label, action in group:
                b = Gtk.Button(label=label)
                b.get_child().override_font(Pango.FontDescription("WenQuanYi Zen Hei 40"))
                b.set_can_focus(False)
                b.connect("clicked", self.on_special, action)
                row.pack_start(b, True, True, 0)
                self.specials[action] = b
            self.pack_start(row, True, True, 0)

    def build_letters(self):
        for r in self.letter_rows:
            for c in r.get_children():
                r.remove(c)
        self.keys = {}
        rows = self.SYM_ROWS if self.sym else self.ROWS
        for r, chars in zip(self.letter_rows, rows):
            for ch in chars:
                r.pack_start(self.key(ch), True, True, 0)
        self.show_all()

    def key(self, ch):
        b = Gtk.Button(label=ch)
        b.get_child().override_font(Pango.FontDescription("WenQuanYi Zen Hei 48"))
        b.set_can_focus(False)
        b.connect("clicked", self.on_char, ch)
        self.keys[ch] = b
        return b

    def _log(self, kind, val):
        if not os.environ.get("PRO6_TEST"):
            return
        try:
            with open("/tmp/pro6_kbd.log", "a") as f:
                f.write(f"{kind} {val} focused={type(getattr(self, 'focused', None)).__name__}\n")
        except Exception:
            pass

    def target_entry(self):
        w = getattr(self, "focused", None)
        if isinstance(w, Gtk.Entry) and w.get_mapped():
            return w
        w = self.app.window.get_focus()
        if isinstance(w, Gtk.Entry):
            return w
        return None

    @staticmethod
    def _entry_insert(e, text):
        pos = e.get_position()
        try:
            e.delete_selection()
            pos = e.get_position()
        except Exception:
            pass
        try:
            e.insert_text(text, pos)
        except Exception:
            t = e.get_text()
            e.set_text(t[:pos] + text + t[pos:])
        e.set_position(pos + len(text))

    def on_char(self, _b, ch):
        self._log("char", ch)
        e = self.target_entry()
        if e:
            self._entry_insert(e, ch.upper() if self.shift else ch)
            return
        out = ch.upper() if self.shift else ch
        if self.ctrl and out.isalpha():
            out = chr(ord(out.lower()) - 96)
        self.app.term.feed_child(out.encode())

    def on_special(self, _b, action):
        self._log("special", action)
        e = self.target_entry()
        if action == "shift":
            self.shift = not self.shift
            return
        if action == "ctrl":
            self.ctrl = not self.ctrl
            return
        if action == "sym":
            self.sym = not self.sym
            self.specials["sym"].set_label("字母" if self.sym else "符号")
            self.build_letters()
            return
        if e:
            if action == "bs":
                if not e.delete_selection():
                    pos = e.get_position()
                    if pos > 0:
                        e.delete_text(pos - 1, pos)
            elif action == "enter":
                e.activate()
            elif action == "space":
                self._entry_insert(e, " ")
            elif action == "tab":
                self.app.window.set_focus(e.get_next_focus() or e)
            elif len(action) == 1:
                self._entry_insert(e, action)
            return
        seqs = {
            "bs": b"\x7f", "enter": b"\r", "tab": b"\t", "esc": b"\x1b",
            "up": b"\x1b[A", "down": b"\x1b[B",
            "left": b"\x1b[D", "right": b"\x1b[C",
            "space": b" ",
        }
        if len(action) == 1:
            self.app.term.feed_child(action.encode())
        elif action in seqs:
            self.app.term.feed_child(seqs[action])


class ConsoleApp:
    def __init__(self):
        self.window = Gtk.Window(title="PRO6 控制台")
        self.window.connect("destroy", Gtk.main_quit)
        if os.environ.get("PRO6_TEST"):
            def _evtlog(_w, evt):
                try:
                    with open("/tmp/pro6_evt.log", "a") as f:
                        f.write(f"{evt.type.value_nick}\n")
                except Exception:
                    pass
                return False
            self.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.window.connect("event", _evtlog)

        self.window.maximize()
        apply_css()

        # kiosk-shell fullscreen hides CSD titlebars, so the page switcher
        # lives inside the window content, not in set_titlebar()
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                         margin=8)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.nav_buttons = {}
        for name, label in [("monitor", "监控"), ("wifi", "Wi-Fi"), ("term", "终端")]:
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, n=name: self._goto(n))
            header.pack_start(b, True, True, 0)
            self.nav_buttons[name] = b

        self.overlay = Gtk.Overlay()
        self.overlay.add(self.stack)
        self.err_panel = Gtk.Frame()
        eb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                     margin=20)
        self.err_text = Gtk.Label(xalign=0)
        self.err_text.set_line_wrap(True)
        self.err_ok = Gtk.Button(label="确定")
        self.err_ok.connect("clicked", lambda *_: self.hide_error())
        eb.pack_start(self.err_text, False, False, 0)
        eb.pack_start(self.err_ok, False, False, 0)
        self.err_panel.add(eb)
        self.err_panel.set_halign(Gtk.Align.CENTER)
        self.err_panel.set_valign(Gtk.Align.CENTER)
        self.err_panel.set_no_show_all(True)
        self.overlay.add_overlay(self.err_panel)

        self.power_panel = Gtk.Frame()
        pb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                     margin=20)
        pb.pack_start(Gtk.Label(label="电源"), False, False, 0)
        self.power_off_btn = Gtk.Button(label="关机")
        self.power_reboot_btn = Gtk.Button(label="重启")
        self.power_cancel_btn = Gtk.Button(label="取消")
        self.power_off_btn.connect("clicked",
                                   lambda *_: self._power_action("poweroff"))
        self.power_reboot_btn.connect("clicked",
                                      lambda *_: self._power_action("reboot"))
        self.power_cancel_btn.connect("clicked", lambda *_: self.hide_power_menu())
        pb.pack_start(self.power_off_btn, False, False, 0)
        pb.pack_start(self.power_reboot_btn, False, False, 0)
        pb.pack_start(self.power_cancel_btn, False, False, 0)
        self.power_panel.add(pb)
        self.power_panel.set_halign(Gtk.Align.CENTER)
        self.power_panel.set_valign(Gtk.Align.CENTER)
        self.power_panel.set_no_show_all(True)
        self.overlay.add_overlay(self.power_panel)

        self.monitor = MonitorPage()
        self.wifi = WifiPage(self)
        self.stack.add_named(self.monitor, "monitor")
        self.stack.add_named(self.wifi, "wifi")

        # terminal page: VTE + on-screen keyboard
        termbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.term = Vte.Terminal()
        self.term.set_font(Pango.FontDescription("WenQuanYi Zen Hei Mono 18"))
        self.term.set_scrollback_lines(5000)
        self.term.spawn_async(
            Vte.PtyFlags.DEFAULT, os.environ.get("HOME", "/root"),
            ["/bin/bash", "-i"], [], GLib.SpawnFlags.DEFAULT,
            None, None, -1, None, None, None)
        termbox.pack_start(self.term, True, True, 0)
        self.stack.add_named(termbox, "term")

        self.kbd = KeyboardPanel(self)
        def _on_set_focus(_w, f):
            if isinstance(f, Gtk.Entry):
                self.kbd.focused = f
        self.window.connect("set-focus", _on_set_focus)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(header, False, False, 0)
        root.pack_start(self.overlay, True, True, 0)
        root.pack_start(self.kbd, False, False, 0)
        self.window.add(root)
        self.window.show_all()

        GLib.timeout_add(MON_INTERVAL, self._tick)
        self._start_power_key_watch()

    SCREEN_STATE = "/tmp/pro6_screen_state"

    def screen_on(self):
        return read(self.SCREEN_STATE) != "off"

    def toggle_screen(self):
        new = "off" if self.screen_on() else "on"
        try:
            with open(self.SCREEN_STATE, "w") as f:
                f.write(new)
        except OSError:
            pass

    def _wake_screen(self):
        if not self.screen_on():
            self.toggle_screen()
        return False

    def show_power_menu(self):
        if not self.screen_on():
            self.toggle_screen()
        self.power_panel.set_no_show_all(False)
        self.power_panel.show_all()

    def hide_power_menu(self):
        self.power_panel.hide()

    def _power_action(self, action):
        self.hide_power_menu()
        sh(["systemctl", action])

    def _start_power_key_watch(self):
        threading.Thread(target=self._power_watch, daemon=True).start()

    SCREEN_IDLE_SEC = int(os.environ.get("PRO6_SCREEN_IDLE_SEC", "300"))

    def _idle_check(self):
        # auto screen-off: no input for SCREEN_IDLE_SEC while the panel is on.
        # The server itself never sleeps — only the display blanks.
        if self.screen_on() and \
                time.monotonic() - self._last_input > self.SCREEN_IDLE_SEC:
            self.toggle_screen()
        return True

    def _power_watch(self):
        import glob
        import select
        import struct
        fmt = "@llHHi"
        size = struct.calcsize(fmt)
        fds = {}
        self._last_input = time.monotonic()
        GLib.timeout_add_seconds(10, self._idle_check)
        while True:
            for p in glob.glob("/dev/input/event*"):
                if p in fds:
                    continue
                try:
                    fds[p] = os.open(p, os.O_RDONLY)
                except OSError:
                    pass
            try:
                ready, _, _ = select.select(list(fds.values()), [], [], 1.0)
            except (OSError, ValueError):
                fds.clear()
                continue
            for fd in ready:
                try:
                    data = os.read(fd, size * 16)
                except OSError:
                    data = b""
                if not data:
                    for p, f in list(fds.items()):
                        if f == fd:
                            del fds[p]
                    continue
                for i in range(0, len(data) - size + 1, size):
                    s, u, typ, code, val = struct.unpack(fmt, data[i:i+size])
                    if typ != 0:  # any real event = user activity
                        self._last_input = time.monotonic()
                        if not self.screen_on() and typ in (1, 3):
                            # touch or key wakes the blanked panel
                            GLib.idle_add(self._wake_screen)
                    if typ == 1 and code in (116, 172):  # KEY_POWER / KEY_HOME (mBack)
                        ts = s + u / 1e6  # kernel event timestamp
                        attr = "_power_press" if code == 116 else "_home_press"
                        if val == 1:
                            # mBack line bounces: collapse a press burst
                            if code == 172 and \
                                    ts - getattr(self, "_home_last", 0.0) < 0.4:
                                pass
                            else:
                                if code == 172:
                                    self._home_last = ts
                                setattr(self, attr, ts)
                        elif val == 0:
                            press = getattr(self, attr, None)
                            setattr(self, attr, None)
                            if press is not None:
                                dur = ts - press
                                if dur >= 5.0:
                                    GLib.idle_add(self.show_power_menu)
                                else:
                                    GLib.idle_add(self.toggle_screen)

    def show_error(self, text):
        self.err_text.set_text(text)
        self.err_panel.set_no_show_all(False)
        self.err_panel.show_all()

    def hide_error(self):
        self.err_panel.hide()

    def _goto(self, name):
        if name == "term":
            self.kbd.focused = None
        self.stack.set_visible_child_name(name)

    def _tick(self):
        name = self.stack.get_visible_child_name()
        if name == "monitor":
            self.monitor.tick_countdown()
        elif name == "wifi":
            self.wifi.refresh_status()
        if os.environ.get("PRO6_TEST"):
            self._dump()
        return True

    def _dump(self):
        import json
        def rect(w):
            if not w.get_mapped():
                return None
            a = w.get_allocation()
            pos = w.translate_coordinates(self.window, 0, 0)
            if pos is None:
                return None
            x, y = pos
            return [x, y, a.width, a.height]
        f = getattr(self.kbd, "focused", None)
        d = {"page": self.stack.get_visible_child_name(),
             "focused": type(f).__name__ if f else None,
             "nav": {n: rect(b) for n, b in self.nav_buttons.items()},
             "kbd": {c: rect(b) for c, b in self.kbd.keys.items()},
             "special": {a: rect(b) for a, b in self.kbd.specials.items()},
             "term": rect(self.term)}
        d["screen"] = "on" if self.screen_on() else "off"
        d["power_menu"] = ({"off": rect(self.power_off_btn),
                            "reboot": rect(self.power_reboot_btn),
                            "cancel": rect(self.power_cancel_btn)}
                           if self.power_panel.get_visible() else None)
        if d["page"] == "monitor":
            d["monitor"] = {"refresh": rect(self.monitor.refresh_btn),
                            "reboot": rect(self.monitor.reboot_btn),
                            "power": rect(self.monitor.power_btn),
                            "reboot_label": self.monitor.reboot_btn.get_label(),
                            "power_label": self.monitor.power_btn.get_label(),
                            "countdown": self.monitor.count_lbl.get_text()}
        if d["page"] == "wifi":
            rows = []
            for r in self.wifi.listbox.get_children():
                if hasattr(r, "ssid"):
                    rows.append({"ssid": r.ssid, "open": r.open,
                                 "rect": rect(r)})
            d["wifi"] = {"status": self.wifi.status.get_text(),
                         "dialog": ({"text": self.err_text.get_text(),
                                     "ok": rect(self.err_ok)}
                                    if self.err_panel.get_visible()
                                    else None),
                         "selected": self.wifi.ssid_lbl.get_text(),
                         "entry": rect(self.wifi.pass_entry),
                         "entry_text": self.wifi.pass_entry.get_text(),
                         "scan": rect(self.wifi.scan_btn),
                         "connect": rect(self.wifi.connect_btn),
                         "rows": rows}
        try:
            with open("/tmp/pro6_test_dump.tmp", "w") as f:
                json.dump(d, f)
            os.replace("/tmp/pro6_test_dump.tmp", "/tmp/pro6_test_dump.json")
        except Exception:
            pass


if __name__ == "__main__":
    ConsoleApp()
    Gtk.main()
