# VLM Cosplay 角色识别 Benchmark

测试多个视觉语言模型（VLM）在 cosplay 角色识别任务上的 naive 表现——不给任何参考图或候选列表，纯粹依靠模型自身的视觉理解能力。

## 流程

1. **角色选取**：从 `characters_ranked.json` 中选取 rank = 100, 200, …, 1000 共 10 个角色；若某 rank 搜不到图则顺位 +1 ~ +4
2. **Cosplay 图搜索**：复用 brief_names + Bing 搜索，每个角色获取 1 张 cosplay 图
3. **VLM 识别**：对每张图用 chain-of-thought prompt 逐步推理，输出：
   - `caption`：人物外观描述
   - `analysis`：推理分析
   - `character_name`：识别出的角色名
   - `bangumi_name`：识别出的番剧/游戏名
4. **评分与报告**：模糊匹配预测与 ground truth，生成 Markdown 报告

## 测试模型

| 模型 | 后端 | 说明 |
|------|------|------|
| gemini-3-flash | Gemini（自定义 Base URL） | Google Gemini 快速视觉模型 |
| gpt-5-mini | OpenAI 兼容接口 | OpenAI 视觉模型 |
| GLM-4.6V-FlashX | ZhiPu (直连) | 智谱清言视觉模型 |
| claude-haiku | Anthropic（待可用端点） | Anthropic Claude Haiku |

## 使用

```bash
# 列出可用模型
python -m src.vlm_benchmark.benchmark --list-models

# 运行完整 benchmark（所有可用模型）
python -m src.vlm_benchmark.benchmark

# 指定模型
python -m src.vlm_benchmark.benchmark --models gemini-3-flash gpt-5-mini

# 跳过图片搜索（使用已有图片）
python -m src.vlm_benchmark.benchmark --skip-search
```

## 输出

- `local_data/vlm_benchmark/images/` — 测试用 cosplay 图片
- `local_data/vlm_benchmark/results/{model}/` — 每个模型每个样本的 JSON 结果
- `local_data/vlm_benchmark/benchmark_results.json` — 完整结果
- `information/vlm_benchmark_report.md` — Markdown 评测报告

## 环境变量

在 `.env` 中配置各模型所需的 API Key 与 Base URL。**变量名以 `vlm_clients.py` 里 `MODEL_CONFIGS` 为准**（例如 Gemini / OpenAI 路径会用到成对的 `*_API_KEY` 与 `*_BASE_URL_*`）。智谱直连使用 `GLM_API_KEY`。
