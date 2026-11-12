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

前置：Node.js + Java JDK 17 + Android Studio

```powershell
# 1. 进入目录
cd f:\keyboard\bluetooth-keyboard

# 2. 安装 Capacitor
npm init -y
npm install @capacitor/core @capacitor/cli @capacitor/android

# 3. 添加 Android 平台
npx cap add android

# 4. 同步（把 HTML/JS/CSS 复制到 android 工程）
npx cap sync android

# 5. 打开 Android Studio
npx cap open android

# 6. Android Studio: Build → Build APK → 传到平板安装
```

### Capacitor 额外配置（重要：横屏锁定）

打开 `android/app/src/main/AndroidManifest.xml`，在 `<activity>` 里加：

```xml
android:screenOrientation="sensorLandscape"
android:configChanges="orientation|screenSize|keyboardHidden"
android:resizeableActivity="false"
```

### 沉浸式全屏（Edge-to-Edge）

`android/app/src/main/res/values/styles.xml`：

```xml
<item name="android:windowLayoutInDisplayCutoutMode">shortEdges</item>
<item name="android:windowTranslucentStatus">true</item>
<item name="android:windowTranslucentNavigation">true</item>
```

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
