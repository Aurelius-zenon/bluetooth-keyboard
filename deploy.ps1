# Deploy Bluetooth Keyboard PWA to GitHub
# Usage: .\deploy.ps1 -GitHubUser Aurelius-zenon
# NOTE: This file is ASCII-only on purpose. PowerShell 5.1 reads .ps1 as ANSI
#       when there is no BOM, which corrupts non-ASCII text and breaks parsing.

param(
    [Parameter(Mandatory = $true)]
    [string]$GitHubUser,

    [string]$RepoName = "bluetooth-keyboard"
)

$ErrorActionPreference = "Stop"

function Line {
    Write-Host "========================================" -ForegroundColor Cyan
}

Write-Host ""
Line
Write-Host "  Bluetooth Keyboard - Deploy to GitHub" -ForegroundColor Cyan
Line
Write-Host ""

# ---- Step 1: create repo ----
$createUrl = "https://github.com/new?name=$RepoName&visibility=public"
Write-Host "[1/4] Create a PUBLIC repo in your browser:" -ForegroundColor Yellow
Write-Host "      $createUrl" -ForegroundColor White
Write-Host ""
Write-Host "      - Repository name: $RepoName" -ForegroundColor Gray
Write-Host "      - Visibility: Public (required, PWABuilder needs public URL)" -ForegroundColor Gray
Write-Host "      - Do NOT check 'Add README' / 'Add .gitignore'" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter after the repo is created"

# ---- Step 2: push ----
Write-Host ""
Write-Host "[2/4] Pushing code to GitHub..." -ForegroundColor Yellow

$remote = "https://github.com/$GitHubUser/$RepoName.git"
$existing = git remote get-url origin 2>$null
if ($existing) {
    Write-Host "      origin exists, updating to $remote" -ForegroundColor Gray
    git remote set-url origin $remote
} else {
    git remote add origin $remote
}

git branch -M main
git push -u origin main --force
Write-Host "      OK - pushed" -ForegroundColor Green

# ---- Step 3: enable GitHub Pages ----
$pagesUrl = "https://github.com/$GitHubUser/$RepoName/settings/pages"
Write-Host ""
Write-Host "[3/4] Enable GitHub Pages:" -ForegroundColor Yellow
Write-Host "      Open: $pagesUrl" -ForegroundColor White
Write-Host "      Source : Deploy from a branch" -ForegroundColor Gray
Write-Host "      Branch : main / (root)" -ForegroundColor Gray
Write-Host "      Click Save" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter after saving (wait 1-2 min for first build)"

# ---- Step 4: PWABuilder ----
$pwaUrl = "https://$GitHubUser.github.io/$RepoName/"
$pwabuilderUrl = "https://www.pwabuilder.com/reportcard?site=$pwaUrl"

Write-Host ""
Write-Host "[4/4] Generate APK with PWABuilder:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Your PWA URL:" -ForegroundColor Green
Write-Host "  $pwaUrl" -ForegroundColor White
Write-Host ""
Write-Host "  PWABuilder:" -ForegroundColor Green
Write-Host "  $pwabuilderUrl" -ForegroundColor White
Write-Host ""
Write-Host "  Steps:" -ForegroundColor Gray
Write-Host "    1. Open the PWABuilder link above" -ForegroundColor Gray
Write-Host "    2. Wait for the scan to finish" -ForegroundColor Gray
Write-Host "    3. Click 'Package for Stores' -> Android" -ForegroundColor Gray
Write-Host "    4. Package id: com.bluetoothkeyboard.app" -ForegroundColor Gray
Write-Host "    5. Generate -> download the APK" -ForegroundColor Gray
Write-Host "    6. Copy to your tablet and install" -ForegroundColor Gray
Write-Host ""
Line
Write-Host "  Done. Install the APK on Xiaomi Pad 7 Pro." -ForegroundColor Cyan
Line
Write-Host ""
