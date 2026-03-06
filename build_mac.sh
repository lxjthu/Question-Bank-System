#!/usr/bin/env bash
# ============================================================
# build_mac.sh — 试题管理系统 macOS DMG 构建脚本
#
# 使用方法（在 Mac 上执行）：
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# 产物：
#   dist/试题管理系统_v1.7.0_arm64.dmg
#
# 要求：
#   - macOS 12+，Apple Silicon（M1/M2/M3）
#   - Python 3.10+ (arm64 原生版，非 Rosetta)
#   - 无需预先安装任何依赖（脚本自动创建隔离 venv）
# ============================================================
set -euo pipefail

APP_NAME="试题管理系统"
VERSION="1.7.0"
DMG_NAME="${APP_NAME}_v${VERSION}_arm64.dmg"
VENV_DIR=".build_venv"
DIST_APP="dist/${APP_NAME}.app"

# ── 检查平台 ──────────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "❌ 此脚本只能在 macOS 上运行。"
    exit 1
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
    echo "⚠️  当前架构为 ${ARCH}，非 arm64。"
    echo "   如在 Rosetta 下运行，请退出终端并用原生终端重启。"
    read -r -p "   是否继续？[y/N] " yn
    [[ "$yn" =~ ^[Yy] ]] || exit 1
fi

# ── 检查 Python ───────────────────────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    echo "❌ 未找到 Python 3，请先安装（推荐从 python.org 下载 arm64 版）。"
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ 使用 Python $PY_VER（$(which "$PYTHON")）"

PY_ARCH=$("$PYTHON" -c "import platform; print(platform.machine())")
if [[ "$PY_ARCH" != "arm64" ]]; then
    echo "⚠️  Python 架构为 ${PY_ARCH}（非 arm64），打包产物可能无法在 M1 上原生运行。"
fi

# ── 创建构建 venv ──────────────────────────────────────────────────────────────
echo ""
echo "📦 创建隔离构建环境：${VENV_DIR}"
"$PYTHON" -m venv "$VENV_DIR"
source "${VENV_DIR}/bin/activate"

pip install --upgrade pip --quiet

echo "📦 安装核心依赖..."
pip install --quiet \
    flask \
    flask-sqlalchemy \
    "python-docx>=1.1" \
    lxml \
    pyinstaller

echo "✅ 依赖安装完成"

# ── PyInstaller 打包 ───────────────────────────────────────────────────────────
echo ""
echo "🔨 开始打包（PyInstaller）..."
rm -rf build dist

pyinstaller exam_system.spec

if [[ ! -d "$DIST_APP" ]]; then
    echo "❌ 打包失败，未生成 ${DIST_APP}"
    exit 1
fi
echo "✅ .app 构建完成：${DIST_APP}"

# ── 创建 DMG ──────────────────────────────────────────────────────────────────
echo ""
echo "💿 创建 DMG..."

DMG_STAGING="dist/.dmg_staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"

# 复制 .app 到暂存区
cp -r "$DIST_APP" "$DMG_STAGING/"

# 创建 Applications 快捷方式（拖入即安装）
ln -s /Applications "$DMG_STAGING/Applications"

# 用 hdiutil 创建压缩 DMG
DMG_OUTPUT="dist/${DMG_NAME}"
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_OUTPUT"

rm -rf "$DMG_STAGING"

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo "🎉 构建成功！"
echo "   DMG 路径：$(pwd)/${DMG_OUTPUT}"
echo ""
echo "安装方法："
echo "  1. 双击打开 ${DMG_NAME}"
echo "  2. 将「${APP_NAME}」拖入「Applications」文件夹"
echo "  3. 双击启动（首次可能需要在「系统设置 → 隐私与安全性」中允许）"
echo ""
echo "数据目录（题库、数据库、导出文件）："
echo "  ~/Library/Application Support/${APP_NAME}/"

deactivate
