#!/bin/bash
# 服务器一键部署脚本（首次 & 更新均可用）
# 用法：bash deploy.sh
set -e

APP_DIR=/root/exam-system-online
SERVICE=exam-system-online

echo "=== 拉取最新代码 ==="
cd "$APP_DIR"
git pull

echo "=== 安装/更新依赖 ==="
source venv/bin/activate
pip install -r requirements.txt -q

echo "=== 重启服务 ==="
systemctl restart "$SERVICE"
systemctl status "$SERVICE" --no-pager
echo "=== 部署完成 ==="
