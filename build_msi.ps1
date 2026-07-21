param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $projectRoot "dist"
$installer = Join-Path $projectRoot "installer"
$assets = Join-Path $projectRoot "assets"
$obj = Join-Path $installer "obj"
$tools = Join-Path $projectRoot ".build-tools\wix314"
$wixArchive = Join-Path $tools "wix314-binaries.zip"
$candle = Join-Path $tools "candle.exe"
$light = Join-Path $tools "light.exe"

New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $obj -Force | Out-Null
New-Item -ItemType Directory -Path $tools -Force | Out-Null

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ArchiveKey --distpath $dist --workpath (Join-Path $projectRoot "build") `
    --specpath (Join-Path $projectRoot "build") `
    --icon (Join-Path $assets "archivekey.ico") `
    --add-data "$assets;assets" (Join-Path $projectRoot "app.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE." }

if (-not (Test-Path -LiteralPath $candle) -or -not (Test-Path -LiteralPath $light)) {
    if (-not (Test-Path -LiteralPath $wixArchive)) {
        gh release download wix3141rtm --repo wixtoolset/wix3 `
            --pattern "wix314-binaries.zip" --dir $tools
        if ($LASTEXITCODE -ne 0) { throw "WiX download failed with exit code $LASTEXITCODE." }
    }
    Expand-Archive -LiteralPath $wixArchive -DestinationPath $tools -Force
}

$wixObject = Join-Path $obj "ArchiveKey.wixobj"
$msi = Join-Path $dist "ArchiveKey-0.4.0-x64.msi"

& $candle -nologo -arch x64 "-dSourceDir=$dist" "-dProjectRoot=$projectRoot" `
    -out $wixObject (Join-Path $installer "ArchiveKey.wxs")
if ($LASTEXITCODE -ne 0) { throw "WiX compilation failed with exit code $LASTEXITCODE." }

& $light -nologo -ext WixUIExtension -cultures:en-us -out $msi $wixObject
if ($LASTEXITCODE -ne 0) { throw "WiX linking failed with exit code $LASTEXITCODE." }

Write-Output $msi
