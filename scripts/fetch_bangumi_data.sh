#!/usr/bin/env bash
# 服务器端运行 Bangumi 数据采集的脚本
# 支持增量抓取: 已处理的番剧和已有详情的角色会自动跳过
#
# 预计时间 (从零开始):
#   Step 1 获取番剧列表: ~1 分钟 (4000 / 50 = 80 页)
#   Step 2 获取角色关联: ~30 分钟 (4000 部番剧)
#   Step 3 补充角色详情: ~8-12 小时 (预计 30000+ 角色)
#   合计: ~12 小时
#
# 用法:
#   chmod +x scripts/fetch_bangumi_data.sh
#   ./scripts/fetch_bangumi_data.sh                          # 默认: top 4000 番剧, top 15000 角色
#   ./scripts/fetch_bangumi_data.sh --top-anime 300          # 只抓 300 部 (本地测试)
#   ./scripts/fetch_bangumi_data.sh --skip-enrich            # 先只拉番剧和角色列表
#   ./scripts/fetch_bangumi_data.sh --output-only            # 仅从缓存重建输出文件

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# 安装依赖
pip install -q -r requirements.txt 2>/dev/null || true

# 确保 .env 存在
if [ ! -f ".env" ]; then
    echo "[WARN] .env 文件不存在，BANGUMI_API_KEY 可能未配置"
fi

LOG_DIR="$PROJECT_ROOT/local_data/bangumi/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/fetch_bangumi_$(date +%Y%m%d_%H%M%S).log"

echo "=============================================="
echo "  Bangumi 数据采集 (v2 - 扩展版)"
echo "=============================================="
echo "  项目目录: $PROJECT_ROOT"
echo "  日志文件: $LOG_FILE"
echo "  额外参数: $*"
echo "=============================================="

PYTHON="${PYTHON:-python3}"
$PYTHON src/bangumi/main.py "$@" 2>&1 | tee "$LOG_FILE"

echo ""
echo "采集完成! 日志已保存至: $LOG_FILE"
