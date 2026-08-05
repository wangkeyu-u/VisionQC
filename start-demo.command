#!/bin/zsh

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$PROJECT_DIR/infra"

clear
echo "VisionQC 演示启动器"
echo "===================="
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker Desktop。"
  echo "1. 浏览器即将打开 Docker Desktop 下载页面。"
  echo "2. 安装并启动 Docker Desktop。"
  echo "3. 再次双击 start-demo.command。"
  open "https://www.docker.com/products/docker-desktop/"
  echo
  read "?按回车键关闭窗口。"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop 尚未启动。正在尝试打开它，请等待鲸鱼图标显示为运行状态。"
  open -a Docker >/dev/null 2>&1 || true
  echo "启动完成后，请再次双击 start-demo.command。"
  echo
  read "?按回车键关闭窗口。"
  exit 1
fi

echo "正在启动 VisionQC。第一次运行需要下载组件，通常需要几分钟……"
cd "$COMPOSE_DIR" || exit 1

if ! docker compose up --build -d; then
  echo
  echo "启动失败。请确认 Docker Desktop 正常运行且电脑可以访问网络。"
  echo "若问题持续，请把本窗口最后 20 行内容发给项目维护者。"
  read "?按回车键关闭窗口。"
  exit 1
fi

echo
echo "服务已经启动，正在等待网页准备好……"
READY=0
for ATTEMPT in {1..60}; do
  if curl --silent --fail http://localhost:3000/ >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done

if [[ "$READY" -eq 1 ]]; then
  echo "VisionQC 已就绪，浏览器即将打开。"
  open "http://localhost:3000/"
  echo
  echo "体验完成后，双击 stop-demo.command 即可安全停止演示。"
else
  echo "服务仍在准备中。请稍后手动打开 http://localhost:3000/"
  echo "如果 5 分钟后仍打不开，请运行：cd infra && docker compose ps"
fi

echo
read "?按回车键关闭本窗口（不会停止 VisionQC）。"
