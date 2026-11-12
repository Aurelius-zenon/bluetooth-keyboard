# 平板蓝牙键盘 · PWA

让平板（小米平板 7 Pro / 任何 Android / iPad）变成电脑的蓝牙键盘。

打开网页 → 添加到主屏幕 → 全屏横屏 → 按键实时输入到电脑。

## 在线体验

https://<你的用户名>.github.io/bluetooth-keyboard/

## 本地运行

```bash
# 电脑端：启动桥接服务（让按键真的注入到电脑全局）
python bridge.py --port 8888

# 静态托管：手机/平板访问原型
python -m http.server 8090
```

平板 Chrome 打开 `http://<电脑IP>:8090` → 添加到主屏幕 → 全屏 App 体验。

## 联调桥接

原型里：设置 → 联调桥接 → 启用 → 填 `http://<电脑IP>:8888`

按键协议（HTTP POST /key）：
```json
{"key": "c", "mods": ["ctrl"], "combo": "ctrl+c", "label": "Ctrl+C 复制"}
{"key": "enter", "mods": [], "combo": null, "label": "Enter"}
```

电脑端桥接用 **ctypes SendInput**（Windows 原生 API），单键 ≈4ms，组合键 ≈20ms。

## 功能

- ✅ 61 键精简 / 78 键完整（含小键盘）一键切换
- ✅ 全局组合键：Win+R / Win+D / Alt+Tab / Ctrl+C/V/Z/F …
- ✅ 3 套主题（亮色 / 深色 / 米色）
- ✅ 横屏沉浸式（小米平板 7 Pro safe-area 适配）
- ✅ 离线可用（Service Worker）
- ✅ 零依赖（纯 HTML/CSS/JS + Python 标准库）

## 打包成 APK

详见 [BUILD.md](./BUILD.md) —— 三种方案：
1. **PWA 添加到主屏幕**（最快，零成本）
2. **PWABuilder 在线生成 APK**（微软官方工具，无需 Android Studio）
3. **Capacitor + Android Studio**（完整原生）

## 文件结构

```
bluetooth-keyboard/
├── index.html            # 键盘原型（PWA-ready）
├── manifest.webmanifest  # PWA 清单（横屏锁定）
├── sw.js                 # Service Worker（离线缓存）
├── bridge.py             # 电脑端桥接服务（ctypes SendInput）
├── capacitor.config.json # Capacitor APK 打包配置
└── BUILD.md              # 打包指南
```

## 技术栈

- 前端：纯 HTML/CSS/JS（零依赖，单文件）
- PWA：manifest + Service Worker（横屏 standalone）
- 桥接：Python ctypes + Windows SendInput API + ThreadingHTTPServer
- 性能：生产者-消费者队列，HTTP 入队即返回（≈1ms），单键 ≈4ms

## License

MIT
