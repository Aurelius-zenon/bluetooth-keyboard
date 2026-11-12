"""
平板蓝牙键盘 · 高性能桥接服务
=============================
零依赖：只用到 Python 标准库（ctypes + http.server + queue + threading）
底层：Windows SendInput API（绕过 pyautogui 的 100ms 默认 PAUSE）

架构（端口-适配器模式）：
  HTTP ThreadingHTTPServer ──入队(立即返回)──▶ Queue ──单消费者线程──▶ ctypes SendInput

用法:
    python bridge.py [--port 8888]

性能目标:
  单键 ≈ 4ms · 组合键 ≈ 15ms · 并发无阻塞 · 组合键原子性保证
"""

import argparse
import ctypes
import json
import mimetypes
import os
import queue
import socket
import ssl
import sys
import threading
import time
from ctypes import wintypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

STATIC_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_FILES = {
    '/index.html', '/manifest.webmanifest', '/sw.js',
}

# TLS 证书文件（--gen-cert 生成）
CA_CERT_FILE = os.path.join(STATIC_ROOT, 'ca.crt')
SERVER_CERT_FILE = os.path.join(STATIC_ROOT, 'server.crt')
SERVER_KEY_FILE = os.path.join(STATIC_ROOT, 'server.key')


def _local_ips():
    """收集本机所有 IPv4，用于证书 SAN"""
    ips = {'127.0.0.1'}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(ips)


def gen_cert():
    """生成本地 CA + 服务器证书（SAN 含本机所有 IP）"""
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        print("需要 cryptography 库：pip install cryptography")
        return False

    now = datetime.datetime.now(datetime.timezone.utc)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'TouchKeyboard Local CA')])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sans = [x509.DNSName('localhost')]
    for ip in _local_ips():
        sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'touch-keyboard-bridge')]))
        .issuer_name(ca_cert.subject)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(srv_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    with open(CA_CERT_FILE, 'wb') as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))
    with open(SERVER_CERT_FILE, 'wb') as f:
        f.write(srv_cert.public_bytes(serialization.Encoding.PEM))
    with open(SERVER_KEY_FILE, 'wb') as f:
        f.write(srv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    print()
    print("证书已生成：")
    print(f"  {CA_CERT_FILE}      ← 传到平板安装为「CA 证书」")
    print(f"  {SERVER_CERT_FILE}")
    print(f"  {SERVER_KEY_FILE}")
    print()
    print("SAN 覆盖的地址：localhost, " + ', '.join(_local_ips()))
    print()
    return True

# ---------------------------------------------------------------------------
# 0. 类型定义（SendInput 需要的 ctypes 结构体）
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004  # 暂未用，保留

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk",         wintypes.WORD),
        ("wScan",       wintypes.WORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class MouseInput(ctypes.Structure):
    """必须声明！x64 下 MOUSEINPUT 是 32 字节，决定了 sizeof(INPUT)=40"""
    _fields_ = [
        ("dx",          wintypes.LONG),
        ("dy",          wintypes.LONG),
        ("mouseData",   wintypes.DWORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg",    wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u",    InputUnion),
    ]

# ---------------------------------------------------------------------------
# 1. 虚拟键码映射（US Keyboard Layout）
# ---------------------------------------------------------------------------

VK_CODE: dict[str, int] = {
    # 修饰键
    'ctrl':  0x11, 'control': 0x11,
    'alt':   0x12, 'menu':     0x12,
    'shift': 0x10,
    'win':   0x5B, 'meta': 0x5B, 'cmd': 0x5B, 'super': 0x5B,  # Win 键
    'win_r': 0x5C,

    # 功能键
    'escape':    0x1B, 'esc':      0x1B,
    'enter':     0x0D, 'return':   0x0D,
    'tab':       0x09,
    'space':     0x20, 'spacebar': 0x20,
    'backspace': 0x08,
    'delete':    0x2E, 'del':      0x2E,

    # 方向键
    'left':  0x25, 'up':    0x26, 'right': 0x27, 'down':  0x28,

    # 导航
    'home':     0x24, 'end':       0x23,
    'pageup':   0x21, 'pagedown':  0x22,

    # F 键
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10':0x79, 'f11':0x7A, 'f12':0x7B,
}

# 数字 0-9
for _i in range(10):
    VK_CODE[str(_i)] = 0x30 + _i

# 字母 a-z —— 注意：VK 码是大写 0x41-0x5A，小写 0x61-0x69 是 VK_NUMPAD1..9
for _c in range(ord('a'), ord('z') + 1):
    VK_CODE[chr(_c)] = ord(chr(_c).upper())  # a=0x41, b=0x42 ... z=0x5A

# 符号键（US layout virtual key codes）
VK_CODE.update({
    '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE,
    ',': 0xBC, '.': 0xBE, '/': 0xBF,
    '-': 0xBD, '=': 0xBB, '`': 0xC0,
})

# Shift 态符号：prototype 发来的是 shift 后的符号，需要转成基键
SHIFT_SYMBOL_TO_BASE: dict[str, tuple[str, str]] = {
    '!':  ('1', 'shift'),
    '@':  ('2', 'shift'),
    '#':  ('3', 'shift'),
    '$':  ('4', 'shift'),
    '%':  ('5', 'shift'),
    '^':  ('6', 'shift'),
    '&':  ('7', 'shift'),
    '*':  ('8', 'shift'),
    '(':  ('9', 'shift'),
    ')':  ('0', 'shift'),
    '_':  ('-', 'shift'),
    '+':  ('=', 'shift'),
    '{':  ('[', 'shift'),
    '}':  (']', 'shift'),
    '|':  ('\\','shift'),
    ':':  (';', 'shift'),
    '"':  ("'", 'shift'),
    '<':  (',', 'shift'),
    '>':  ('.', 'shift'),
    '?':  ('/', 'shift'),
    '~':  ('`', 'shift'),
}


# ---------------------------------------------------------------------------
# 2. SendInput 底层
# ---------------------------------------------------------------------------

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_user32.SendInput.restype = ctypes.c_uint
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.SetFocus.argtypes = [wintypes.HWND]
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# 运行统计（供 /diag 查询，用于定位"按键到底发给谁了"）
_stats = {
    'sent': 0, 'failed': 0,
    'last_key': '', 'last_combo': '', 'last_fg': '',
    'last_ok': None, 'last_err': 0, 'last_ts': 0.0,
    'elevated': False,
}
_last_foreground = ''


def send_vk(vk_code: int, is_up: bool = False) -> bool:
    """发送一个虚拟键码 keyDown 或 keyUp，返回是否成功"""
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki.wVk = vk_code
    inp.ki.wScan = 0
    inp.ki.dwFlags = KEYEVENTF_KEYUP if is_up else 0
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        _stats['failed'] += 1
        _stats['last_err'] = ctypes.get_last_error()
        return False
    return True


def _foreground_title() -> str:
    """当前前台窗口标题 —— SendInput 只会把键发到这里"""
    try:
        hwnd = _user32.GetForegroundWindow()
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value or '(无标题窗口)'
    except Exception:
        return '(读取失败)'


# ---- 目标窗口锁定（解决"焦点被终端抢走"的问题）----
_target_hwnd = 0


def _hwnd_title(hwnd) -> str:
    try:
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value or '(无标题窗口)'
    except Exception:
        return '(读取失败)'

_USER32_EXTRA = {
    'SetForegroundWindow': ([wintypes.HWND], ctypes.c_bool),
    'ShowWindow': ([wintypes.HWND, ctypes.c_int], ctypes.c_bool),
    'IsIconic': ([wintypes.HWND], ctypes.c_bool),
    'IsWindow': ([wintypes.HWND], ctypes.c_bool),
    'IsWindowVisible': ([wintypes.HWND], ctypes.c_bool),
}
for _name, (_args, _ret) in _USER32_EXTRA.items():
    _fn = getattr(_user32, _name)
    _fn.argtypes = _args
    _fn.restype = _ret


def list_windows():
    """枚举有标题的可见顶层窗口"""
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    items = []

    def _cb(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            n = _user32.GetWindowTextLengthW(hwnd)
            if n == 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            _user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            items.append({'hwnd': int(hwnd), 'title': buf.value, 'pid': pid.value})
        except Exception:
            pass
        return True

    _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return items


def _alt_unlock():
    """按一下 Alt，绕过 Windows 的 SetForegroundWindow 限制"""
    try:
        _user32.keybd_event(0x12, 0, 0, 0)
        _user32.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass


def focus_target() -> bool:
    """把锁定的目标窗口切到前台。

    Windows 禁止后台进程直接 SetForegroundWindow，
    需要先 AttachThreadInput 到目标线程再调用，才能稳定生效。
    """
    global _target_hwnd
    if not _target_hwnd:
        return False
    hwnd = _target_hwnd
    try:
        if not _user32.IsWindow(hwnd):
            _target_hwnd = 0
            return False
        if _user32.GetForegroundWindow() == hwnd:
            return True

        for _ in range(3):
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            else:
                _user32.ShowWindow(hwnd, 5)   # SW_SHOW
            _user32.BringWindowToTop(hwnd)

            fg = _user32.GetForegroundWindow()
            cur_tid = _kernel32.GetCurrentThreadId()
            fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
            tgt_tid = _user32.GetWindowThreadProcessId(hwnd, None)

            attached = []
            for tid in {fg_tid, tgt_tid}:
                if tid and tid != cur_tid:
                    if _user32.AttachThreadInput(cur_tid, tid, True):
                        attached.append(tid)
            try:
                _user32.SetForegroundWindow(hwnd)
                _user32.SetFocus(hwnd)
            finally:
                for tid in attached:
                    _user32.AttachThreadInput(cur_tid, tid, False)

            if _user32.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.02)

        # 最后手段：SwitchToThisWindow（对后台进程抢前台更宽容）
        try:
            _user32.SwitchToThisWindow(hwnd, True)
        except Exception:
            pass
        if _user32.GetForegroundWindow() == hwnd:
            return True

        # 再兜底：Alt 解锁后重试
        _alt_unlock()
        _user32.SetForegroundWindow(hwnd)
        return _user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def press_vk(vk_code: int) -> bool:
    """单次按键：keyDown → keyUp"""
    a = send_vk(vk_code, is_up=False)
    b = send_vk(vk_code, is_up=True)
    return a and b


# ---------------------------------------------------------------------------
# 3. 组合键原子发送 —— 全部 mod down → press main → 全部 mod up
#    中间不 sleep，让 OS 处理按键时序
# ---------------------------------------------------------------------------

_SEND_GAP = 0.003  # 3ms，SendInput 之间的微小间隔（Windows 需要）


def send_command(command: dict):
    """
    原子发送一个键盘命令。command dict 来自原型 HTTP POST:
      {"key":"c", "mods":["ctrl"], "combo":"ctrl+c", "label":"Ctrl+C 复制"}
      {"key":"win", "mods":[]}                ← 单独 Win 键（不处理）
      {"key":"hello-world", "mods":[]}        ← 测试指令
    """
    raw_key = command.get('key', '')
    mods: list[str] = command.get('mods') or []
    label = command.get('label') or command.get('combo') or raw_key

    # ---- 测试指令 ----
    if raw_key == 'hello-world':
        print(f"  [bridge] 测试 OK → Hello")
        return

    # ---- 跳过裸修饰键 ----
    if raw_key in ('ctrl','alt','shift','win','cmd','win_r') and not mods:
        return

    # ---- 解析修饰键 ----
    mod_vks: list[int] = []
    for m in mods:
        m = m.lower()
        if m in ('cmd','super'): m = 'win'
        code = VK_CODE.get(m)
        if code:
            mod_vks.append(code)

    # ---- 解析主键 ----
    main_vks: list[int] = []  # 可能一个键需要 shift 作为"额外修饰"
    extra_mod_vks: list[int] = []

    # 检查是否是 shift 态符号
    if raw_key in SHIFT_SYMBOL_TO_BASE:
        base, shift_mod = SHIFT_SYMBOL_TO_BASE[raw_key]
        main_vks.append(VK_CODE.get(base, 0))
        extra_mod_vks.append(VK_CODE['shift'])
    else:
        k = raw_key.lower()
        if k in VK_CODE:
            main_vks.append(VK_CODE[k])
        else:
            print(f"  [bridge] ⚠ 未知按键: {raw_key!r}  ({label})")
            return

    # 合并所有需要先 keyDown 的修饰键
    all_down = mod_vks + extra_mod_vks

    # ---- 原子序列 ----
    # 1) 所有修饰键 keyDown（循环，无 sleep）
    for vk in all_down:
        send_vk(vk, is_up=False)

    # 2) 主键 press（Down → Up）
    for vk in main_vks:
        send_vk(vk, is_up=False)
        time.sleep(_SEND_GAP)
        send_vk(vk, is_up=True)
        time.sleep(_SEND_GAP)

    # 3) 所有修饰键 keyUp（反序）
    for vk in reversed(all_down):
        send_vk(vk, is_up=True)
        time.sleep(_SEND_GAP)

    # ---- 日志 ----
    mod_str = '+'.join(m.upper() for m in mods)
    if mod_str:
        print(f"  [bridge] ⌨  {mod_str}+{raw_key.upper() if len(raw_key)==1 else raw_key}  ({label})")
    else:
        print(f"  [bridge] ⌨  {raw_key.upper() if len(raw_key)==1 else raw_key}")


# ---------------------------------------------------------------------------
# 4. 生产者-消费者队列
# ---------------------------------------------------------------------------

_command_queue: queue.Queue = queue.Queue(maxsize=256)


class BridgeServer(ThreadingHTTPServer):
    """单实例：端口被占用时直接报错，避免两个桥接同时注入按键"""
    allow_reuse_address = False
    daemon_threads = True
    allow_reuse_port = False
_start_time = time.monotonic()


def _consumer_loop():
    """单消费者线程：串行消费队列，调用 SendInput"""
    global _last_foreground
    while True:
        cmd = _command_queue.get()
        fg = _foreground_title()
        before_fail = _stats['failed']
        try:
            if _target_hwnd:
                focus_target()
                time.sleep(0.03)   # 等窗口真正激活
            send_command(cmd)
        except Exception as e:
            _stats['failed'] += 1
            _stats['last_err'] = str(e)
            print(f"  [bridge] consumer error: {e}", file=sys.stderr)

        _stats['sent'] += 1
        _stats['last_key'] = cmd.get('key', '')
        _stats['last_combo'] = cmd.get('combo') or ''
        _stats['last_fg'] = fg
        _stats['last_ok'] = (_stats['failed'] == before_fail)
        _stats['last_ts'] = time.time()
        _last_foreground = fg


# ---------------------------------------------------------------------------
# 5. HTTP 适配器（ThreadingHTTPServer，无阻塞入队）
# ---------------------------------------------------------------------------

class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'KeyboardBridge/1.1'

    def log_message(self, fmt, *args):
        pass  # 静默默认日志

    # ---- CORS ----
    def _cors(self, extra: str = ''):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')

    # ---- 预检 ----
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path

        # 状态探针
        if path in ('/ping', '/health'):
            body = json.dumps({
                'ok': True,
                'service': 'keyboard-bridge',
                'queue_size': _command_queue.qsize(),
                'uptime_s': round(time.monotonic() - _start_time, 1),
                'mode': 'ctypes-sendinput',
            }).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 诊断：按键发给了哪个窗口、SendInput 是否成功
        if path == '/diag':
            _t = {'hwnd': _target_hwnd, 'title': ''}
            if _target_hwnd:
                _t['title'] = _hwnd_title(_target_hwnd)
            body = json.dumps({
                'ok': True,
                'foreground': _foreground_title(),
                'target': _t,
                'queue_size': _command_queue.qsize(),
                'elevated': _stats['elevated'],
                'last': {
                    'key': _stats['last_key'],
                    'combo': _stats['last_combo'],
                    'target_window': _stats['last_fg'],
                    'ok': _stats['last_ok'],
                    'err': _stats['last_err'],
                    'ago_s': round(time.time() - _stats['last_ts'], 1) if _stats['last_ts'] else None,
                },
                'sent': _stats['sent'],
                'failed': _stats['failed'],
            }).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 可选目标窗口列表
        if path == '/windows':
            wins = list_windows()
            # 过滤掉过短/无意义的标题
            wins = [w for w in wins if len(w['title'].strip()) >= 1][:40]
            body = json.dumps({'ok': True, 'windows': wins}).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 同源托管网页（彻底避开 https→http 混合内容拦截）
        self._serve_static(path)

    def _serve_static(self, path: str):
        if path == '/':
            path = '/index.html'
        safe = os.path.normpath(path).lstrip('\\/').replace('\\', '/')
        full = os.path.abspath(os.path.join(STATIC_ROOT, safe))
        if not full.startswith(STATIC_ROOT) or not os.path.isfile(full):
            self.send_response(404)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
            return
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if full.endswith('.webmanifest'):
            ctype = 'application/manifest+json'
        with open(full, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('text/', 'application/javascript', 'application/json', 'application/manifest')) else ''))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- POST /key ----
    def do_POST(self):
        global _target_hwnd
        path = urlparse(self.path).path

        # 设置/清除 目标窗口
        if path == '/target':
            try:
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length).decode('utf-8') if length > 0 else '{}'
                data = json.loads(raw or '{}')
                hwnd = int(data.get('hwnd') or 0)
            except Exception as e:
                body = json.dumps({'ok': False, 'error': str(e)}).encode()
                self.send_response(400); self._cors(); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
            _target_hwnd = hwnd
            title = _hwnd_title(hwnd) if hwnd else ''
            body = json.dumps({'ok': True, 'target': {'hwnd': _target_hwnd, 'title': title}}).encode()
            self.send_response(200); self._cors(); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            return

        if path != '/key':
            self.send_response(404); self._cors(); self.send_header('Content-Length','2'); self.end_headers(); self.wfile.write(b'{}')
            return

        # 解析 JSON
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length).decode('utf-8') if length > 0 else ''
            cmd = json.loads(raw) if raw else {}
        except Exception as e:
            body = json.dumps({'ok': False, 'error': f'bad json: {e}'}).encode()
            self.send_response(400); self._cors(); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return

        # 入队（立即返回！不等 SendInput 执行）
        try:
            _command_queue.put_nowait(cmd)
            body = json.dumps({'ok': True, 'queued': True}).encode()
            self.send_response(202)  # 202 Accepted（已入队，不保证执行完成）
        except queue.Full:
            body = json.dumps({'ok': False, 'error': 'queue full'}).encode()
            self.send_response(503)

        self._cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# 6. 入口
# ---------------------------------------------------------------------------

def _minimize_console():
    """把当前控制台最小化，避免它占用前台焦点（SendInput 只发给前台窗口）

    返回 'none' 表示本来就没有控制台（pythonw 静默运行）。
    """
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return 'none'
        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return 'minimized'
    except Exception:
        return 'failed'


def main():
    parser = argparse.ArgumentParser(description='高性能平板触屏键盘桥接')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--bench', action='store_true', help='启动后自动跑 benchmark 测试')
    parser.add_argument('--keep-window', action='store_true', help='不自动最小化控制台')
    parser.add_argument('--tls', action='store_true', help='启用 HTTPS（需先 --gen-cert 生成证书）')
    parser.add_argument('--gen-cert', action='store_true', help='生成本地 CA 与服务器证书后退出')
    args = parser.parse_args()

    if args.gen_cert:
        gen_cert()
        return

    # pythonw 静默运行（无控制台）时 sys.stdout 为 None，重定向到日志文件
    if sys.stdout is None or sys.stderr is None:
        try:
            _log = open(os.path.join(STATIC_ROOT, 'bridge.log'), 'a', encoding='utf-8', buffering=1)
            sys.stdout = _log
            sys.stderr = _log
            print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====")
        except Exception:
            pass

    if args.tls and not (os.path.isfile(SERVER_CERT_FILE) and os.path.isfile(SERVER_KEY_FILE)):
        print("[!] 未找到证书，先自动生成…")
        if not gen_cert():
            return

    # 启动消费者线程（守护）
    consumer = threading.Thread(target=_consumer_loop, name='sendinput-consumer', daemon=True)
    consumer.start()

    try:
        server = BridgeServer((args.host, args.port), BridgeHandler)
    except OSError as e:
        print(f"[!] 端口 {args.port} 无法监听（可能已有一个桥接在运行）：{e}")
        print("    如果平板已经能连上，就不用重复启动。")
        return

    # 取本机局域网 IP
    lan_ip = '127.0.0.1'
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    try:
        _stats['elevated'] = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        _stats['elevated'] = False

    scheme = 'http'
    if args.tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(SERVER_CERT_FILE, SERVER_KEY_FILE)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = 'https'

    # 降级端口：额外开一个纯 HTTP 端口（port+1），HTTPS 出问题时 App 可自动回落
    fallback_port = args.port + 1
    fallback_server = None
    if args.tls:
        try:
            fallback_server = BridgeServer((args.host, fallback_port), BridgeHandler)
            threading.Thread(target=fallback_server.serve_forever, daemon=True).start()
        except OSError as e:
            fallback_server = None
            print(f"  [降级] HTTP 端口 {fallback_port} 未启用：{e}")

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  平板触屏键盘 · 桥接服务 (ctypes SendInput)       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  平板打开:  {scheme}://{lan_ip}:{args.port}/".ljust(52) + "║")
    print(f"║  状态探针:  {scheme}://{lan_ip}:{args.port}/ping".ljust(52) + "║")
    print(f"║  按键接口:  POST /key  (JSON)".ljust(52) + "║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print("  平板与电脑连同一个 WiFi，浏览器打开上面「平板打开」的地址即可")
    print("  该网页与桥接服务同源，不会被浏览器拦截")
    if args.tls:
        print()
        print("  [HTTPS] 首次使用需在平板安装 CA 证书：")
        print(f"         把 {os.path.basename(CA_CERT_FILE)} 传到平板")
        print("         设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书")
        if fallback_server:
            print(f"  [降级]  同时监听 HTTP: http://{lan_ip}:{fallback_port}/  (HTTPS 失败时自动回落)")
    print()
    print("  ★ 按键只会送入【当前前台窗口】")
    print("    先用鼠标点一下目标程序（记事本 / 浏览器输入框等），再按平板键盘")
    print("    切换窗口：平板上按 Alt → Tab")
    print("    要往管理员权限的程序输入：请以管理员身份运行本脚本")
    print()

    if args.bench:
        _run_benchmark()

    if not args.keep_window:
        time.sleep(1.0)
        state = _minimize_console()
        if state == 'minimized':
            print("  [i] 控制台已自动最小化，按键会被送到前台程序")
            print("      想常驻窗口：python bridge.py --keep-window")
        elif state == 'none':
            print("  [i] 后台静默运行（无控制台窗口），日志见 bridge.log")
        else:
            print("  [i] 未能自动最小化，请手动点一下目标窗口")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.server_close()


def _run_benchmark():
    """发送 100 个单键 + 组合键测延迟（直接走 ctypes，不经过 HTTP）"""
    print("=== benchmark (direct ctypes, no HTTP) ===")
    t0 = time.perf_counter()
    for i in range(100):
        press_vk(VK_CODE['x'])
        time.sleep(0.005)  # 模拟用户自然节奏
    t1 = time.perf_counter()
    print(f"  100× press_vk('x'): avg {(t1-t0)/100*1000:.2f}ms  total {(t1-t0)*1000:.0f}ms")

    t0 = time.perf_counter()
    for i in range(20):
        _command_queue.put_nowait({'key':'c','mods':['ctrl']})
        _command_queue.put_nowait({'key':'v','mods':['ctrl']})
    # 等消费者处理完
    while not _command_queue.empty():
        time.sleep(0.001)
    t1 = time.perf_counter()
    print(f"  40× hotkey (Ctrl+C/V via queue): avg {(t1-t0)/40*1000:.2f}ms  total {(t1-t0)*1000:.0f}ms")
    print("=== done ===\n")


if __name__ == '__main__':
    main()
