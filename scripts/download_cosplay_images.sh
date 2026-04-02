#!/bin/bash
# 服务器批量下载 cosplay 图片脚本
# 用法: bash scripts/download_cosplay_images.sh [top_n] [limit] [delay]
#   top_n: 处理前 N 个角色 (默认 1000)
#   limit: 每角色下载图片数 (默认 5)
#   delay: 角色间延迟秒数 (默认 3.0)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TOP_N="${1:-1000}"
LIMIT="${2:-5}"
DELAY="${3:-3.0}"

cd "$PROJECT_ROOT"

if [ ! -f ".env" ]; then
    echo "错误: 未找到 .env 文件，请先配置 WINKY_API_KEY 等环境变量"
    exit 1
fi

echo "============================================"
echo "  Cosplay 图片搜索批量下载"
echo "  角色数量: $TOP_N"
echo "  每角色图片: $LIMIT 张"
echo "  间隔延迟: ${DELAY}s"
echo "============================================"

python3 -m src.cosplay_search.search_cosplay \
    --top-n "$TOP_N" \
    --limit "$LIMIT" \
    --delay "$DELAY"

echo ""
echo "完成! HTML 预览: local_data/cosplay_gallery.html"
