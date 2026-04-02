#!/usr/bin/env bash
# 服务器端运行角色图片下载的脚本
# 预计总耗时 2-3 天（8416 角色 × 2 图 × ~12s 延迟）
#
# 用法:
#   chmod +x scripts/download_character_images.sh
#   ./scripts/download_character_images.sh           # 下载全部角色
#   ./scripts/download_character_images.sh --limit 30 # 只下载前 30 个角色（本地测试）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# 确认数据文件存在
DATA_FILE="local_data/bangumi/characters_ranked.json"
if [ ! -f "$DATA_FILE" ]; then
    echo "[ERROR] 找不到角色数据文件: $DATA_FILE"
    echo "请先运行 python src/bangumi/main.py 采集角色数据"
    exit 1
fi

# 安装依赖（如果尚未安装）
pip install -q -r requirements.txt 2>/dev/null || true

# 设置日志文件
LOG_DIR="$PROJECT_ROOT/local_data/bangumi/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/download_images_$(date +%Y%m%d_%H%M%S).log"

echo "=============================================="
echo "  Bangumi 角色图片下载"
echo "=============================================="
echo "  项目目录: $PROJECT_ROOT"
echo "  数据文件: $DATA_FILE"
echo "  日志文件: $LOG_FILE"
echo "  额外参数: $*"
echo "=============================================="

# 使用 nohup 在后台运行，以免 SSH 断开后中断
# 直接运行（适配 nohup 或 screen/tmux）
PYTHON="${PYTHON:-python3}"
$PYTHON src/bangumi/download_images.py "$@" 2>&1 | tee "$LOG_FILE"

echo ""
echo "下载完成! 日志已保存至: $LOG_FILE"
