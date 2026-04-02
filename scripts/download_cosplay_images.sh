#!/bin/bash
# 服务器批量下载 cosplay 图片 + VLM 验证脚本
# 用法: bash scripts/download_cosplay_images.sh [top_n] [limit] [delay] [--no-vlm]
#   top_n: 处理前 N 个角色 (默认 1000)
#   limit: 每角色下载图片数 (默认 5)
#   delay: 角色间延迟秒数 (默认 3.0)
#   --no-vlm: 只下载不做 VLM 验证

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TOP_N="${1:-1000}"
LIMIT="${2:-5}"
DELAY="${3:-3.0}"
NO_VLM=""

# 检查是否有 --no-vlm 参数
for arg in "$@"; do
    if [ "$arg" = "--no-vlm" ]; then
        NO_VLM="--no-vlm"
    fi
done

cd "$PROJECT_ROOT"

if [ ! -f ".env" ]; then
    echo "错误: 未找到 .env 文件，请先配置环境变量"
    echo "  需要: .env 中 Gemini/OpenAI 兼容调用所需的 API Key 与 Base URL（变量名见对应 Python 模块）"
    exit 1
fi

echo "============================================"
echo "  Cosplay 图片搜索 + VLM 验证"
echo "  角色数量: $TOP_N"
echo "  每角色图片: $LIMIT 张"
echo "  间隔延迟: ${DELAY}s"
if [ -n "$NO_VLM" ]; then
    echo "  VLM 验证: 关闭"
else
    echo "  VLM 验证: 开启 (Gemini)"
fi
echo "============================================"

python3 -m src.cosplay_search.search_cosplay \
    --top-n "$TOP_N" \
    --limit "$LIMIT" \
    --delay "$DELAY" \
    $NO_VLM

echo ""
echo "完成! HTML 预览: local_data/cosplay_gallery.html"
