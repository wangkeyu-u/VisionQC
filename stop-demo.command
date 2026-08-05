#!/bin/zsh

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR/infra" || exit 1

clear
echo "正在安全停止 VisionQC 演示……"

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker，当前没有可停止的演示服务。"
  read "?按回车键关闭窗口。"
  exit 0
fi

if docker compose down; then
  echo
  echo "VisionQC 已停止。演示记录仍保留，下次启动可以继续使用。"
else
  echo
  echo "停止失败。请打开 Docker Desktop，确认它正在运行后重试。"
fi

echo
read "?按回车键关闭窗口。"
