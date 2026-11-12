# 蓝牙键盘 · 小米平板 7 Pro App 打包指南
# ==========================================

## 📱 最快方案：PWA（推荐，10 分钟搞定，零安装）

小米平板 7 Pro 打开 Chrome：
1. 访问原型页面（本地文件 → 开 HTTP 服务；或放到任何静态托管上）
2. 右上角 `⋮` → **「添加到主屏幕」**
3. 桌面出现「蓝牙键盘」图标 → 点开 → **全屏横屏沉浸式**体验
4. 支持离线使用（Service Worker 缓存）

## 📦 APK 方案 A：在线生成（零本地环境，微软 PWABuilder）

1. 把 `bluetooth-keyboard/` 目录上传到任何静态托管（GitHub Pages / Netlify / Vercel）
2. 访问 https://www.pwabuilder.com/ → 输入你的 URL → Start
3. 选 Android → **Package Stores** → 下载生成的 APK
4. 小米平板：设置 → 隐私 → 允许外部安装 → 双击 APK 安装

## 📦 APK 方案 B：本地 Capacitor 打包（需要 Android Studio）

工程已生成在 `android/`，日常只需：

```powershell
cd f:\keyboard\bluetooth-keyboard
npm install          # 首次
npm run sync         # 把 index.html / sw.js / manifest / icons 同步进 www 与 android assets
npm run apk          # 需要 ANDROID_HOME；或在 Android Studio 里 Build APK
```

`npm run apk` 产物：`android/app/build/outputs/apk/debug/app-debug.apk`

### 已内置的原生能力

| 能力 | 实现 |
|------|------|
| 横屏锁定 | `AndroidManifest.xml` → `screenOrientation="sensorLandscape"` |
| 手势锁定 · 沉浸式 | `MainActivity.applyImmersive()`（隐藏系统栏，刘海屏 shortEdges） |
| 手势锁定 · 边缘屏蔽 | `MainActivity.applyExclusion()` → `setSystemGestureExclusionRects`（左右各 200dp，系统上限） |
| 网页调用入口 | `GestureGuardPlugin`（`Capacitor.Plugins.GestureGuard.setLock({on:true})`）+ `window.NativeGestureGuard` 兜底 |
| 局域网 http 桥接 | `res/xml/network_security_config.xml` 允许明文 + 信任用户 CA |
| 屏幕常亮 | `FLAG_KEEP_SCREEN_ON` |

> 系统级边缘返回/三指截屏属于 Android 平台行为，200dp 屏蔽区是系统允许的上限，无法做到全屏屏蔽。

### 📌 部署包须知

`capacitor.config.json` 的 `webDir` 是 `www/`，只打包 `index.html`、`sw.js`、`manifest.webmanifest`、`icons/`；
证书、`bridge.py`、日志不会被塞进 APK。

## 🖥️ 联调模式

平板 App 启动后，进入设置 → 联调桥接 → 启用 → 填电脑 IP：

```
电脑端先跑: python bridge.py --port 8888
平板填:    http://<电脑局域网IP>:8888
```

小米平板查看 IP：设置 → WLAN → 点击已连接的网络 → IP 地址

## 🎯 小米平板 7 Pro 适配已包含

| 特性 | 实现位置 |
|------|---------|
| 横屏锁定 | CSS @media orientation:portrait 提示 + manifest orientation:landscape |
| 沉浸式状态栏 | viewport-fit=cover + env(safe-area-inset-top) |
| 平板大屏 | max-width:1200px 居中 + 按键 ≥52px |
| MIUI Pad 桌面图标 | manifest icons 含 192/512 SVG |
| 离线可用 | Service Worker 缓存 |
