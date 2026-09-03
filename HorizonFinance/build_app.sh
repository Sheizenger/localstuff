#!/usr/bin/env bash
#
# Собирает Горизонт.app из исходников.
#
#   ./build_app.sh              — собрать в ./build
#   ./build_app.sh --install    — собрать и положить в /Applications
#   ./build_app.sh --run        — собрать и сразу запустить
#
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Горизонт"
EXECUTABLE="Horizon"
BUNDLE_ID="com.silantev.horizon"
VERSION="1.0"
BUILD_DIR="build"
APP_PATH="${BUILD_DIR}/${APP_NAME}.app"

INSTALL=0
RUN=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --run) RUN=1 ;;
    *) echo "Неизвестный аргумент: $arg"; exit 1 ;;
  esac
done

if ! command -v swift >/dev/null 2>&1; then
  echo "Не найден swift. Установите инструменты командной строки: xcode-select --install"
  exit 1
fi

echo "▸ Сборка (release)…"
swift build -c release
BIN_PATH="$(swift build -c release --show-bin-path)/${EXECUTABLE}"

echo "▸ Сборка бандла…"
rm -rf "${APP_PATH}"
mkdir -p "${APP_PATH}/Contents/MacOS" "${APP_PATH}/Contents/Resources"
cp "${BIN_PATH}" "${APP_PATH}/Contents/MacOS/${EXECUTABLE}"

cat > "${APP_PATH}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
    <key>CFBundleExecutable</key><string>${EXECUTABLE}</string>
    <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>CFBundleDevelopmentRegion</key><string>ru</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.finance</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSHumanReadableCopyright</key><string>Локальное приложение, данные не покидают компьютер.</string>
</dict>
</plist>
PLIST

# Иконка: PNG → .icns, если под рукой есть штатные утилиты macOS.
if [ -f "Resources/icon.png" ] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  echo "▸ Иконка…"
  ICONSET="${BUILD_DIR}/AppIcon.iconset"
  rm -rf "${ICONSET}"
  mkdir -p "${ICONSET}"
  for size in 16 32 128 256 512; do
    sips -z $size $size Resources/icon.png --out "${ICONSET}/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z $double $double Resources/icon.png --out "${ICONSET}/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "${ICONSET}" -o "${APP_PATH}/Contents/Resources/AppIcon.icns"
  rm -rf "${ICONSET}"
fi

# Подпись «для себя»: без неё macOS ругается на неподписанный бандл при каждом запуске.
if command -v codesign >/dev/null 2>&1; then
  echo "▸ Подпись (ad-hoc)…"
  codesign --force --deep --sign - "${APP_PATH}" >/dev/null 2>&1 || echo "  (подпись пропущена)"
fi

echo "✓ Готово: ${APP_PATH}"

if [ "${INSTALL}" -eq 1 ]; then
  echo "▸ Установка в /Applications…"
  rm -rf "/Applications/${APP_NAME}.app"
  cp -R "${APP_PATH}" "/Applications/${APP_NAME}.app"
  echo "✓ Установлено: /Applications/${APP_NAME}.app"
  if [ "${RUN}" -eq 1 ]; then open "/Applications/${APP_NAME}.app"; fi
elif [ "${RUN}" -eq 1 ]; then
  open "${APP_PATH}"
fi
