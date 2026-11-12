/* 把 Web 资源同步到 www/（Capacitor 的 webDir），避免把证书、日志、脚本打进 APK */
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'www');
const files = ['index.html', 'sw.js', 'manifest.webmanifest'];
const dirs = ['icons'];

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

for (const f of files) {
  fs.copyFileSync(path.join(root, f), path.join(out, f));
}
for (const d of dirs) {
  fs.cpSync(path.join(root, d), path.join(out, d), { recursive: true });
}

console.log('www/ synced:', [...files, ...dirs.map((d) => d + '/')].join(', '));
