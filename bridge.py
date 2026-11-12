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

class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KeyBdInput)]
    _anonymous_ = ("union",)
    _fields_ = [
        ("type",   wintypes.DWORD),
        ("union",  _INPUT),
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

# 字母 a-z
for _c in range(ord('a'), ord('z') + 1):
    VK_CODE[chr(_c)] = _c  # a=0x61, b=0x62 ... z=0x7A

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


def send_vk(vk_code: int, is_up: bool = False):
    """发送一个虚拟键码 keyDown 或 keyUp"""
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki.wVk = vk_code
    inp.ki.wScan = 0
    inp.ki.dwFlags = KEYEVENTF_KEYUP if is_up else 0
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def press_vk(vk_code: int):
    """单次按键：keyDown → keyUp"""
    send_vk(vk_code, is_up=False)
    send_vk(vk_code, is_up=True)


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
_start_time = time.monotonic()


def _consumer_loop():
    """单消费者线程：串行消费队列，调用 SendInput"""
    while True:
        cmd = _command_queue.get()
        try:
            send_command(cmd)
        except Exception as e:
            print(f"  [bridge] ⚠ consumer error: {e}", file=sys.stderr)


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
        path = urlparse(self.path).path
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
    """把当前控制台最小化，避免它占用前台焦点（SendInput 只发给前台窗口）"""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return True
    except Exception:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description='高性能平板触屏键盘桥接')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--bench', action='store_true', help='启动后自动跑 benchmark 测试')
    parser.add_argument('--keep-window', action='store_true', help='不自动最小化控制台')
    args = parser.parse_args()

    # 启动消费者线程（守护）
    consumer = threading.Thread(target=_consumer_loop, name='sendinput-consumer', daemon=True)
    consumer.start()

    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)

    # 取本机局域网 IP
    lan_ip = '127.0.0.1'
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  平板触屏键盘 · 桥接服务 (ctypes SendInput)       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  平板打开:  http://{lan_ip}:{args.port}/".ljust(52) + "║")
    print(f"║  状态探针:  http://{lan_ip}:{args.port}/ping".ljust(52) + "║")
    print(f"║  按键接口:  POST /key  (JSON)".ljust(52) + "║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print("  平板与电脑连同一个 WiFi，浏览器打开上面「平板打开」的地址即可")
    print("  该网页与桥接服务同源，不会被浏览器拦截")
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
        if _minimize_console():
            print("  [i] 控制台已自动最小化，按键会被送到前台程序")
            print("      想常驻窗口：python bridge.py --keep-window")
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
