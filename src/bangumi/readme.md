# Bangumi 数据与角色图

本目录负责 Bangumi API 调研、番剧/角色清单与角色参考图抓取。

## 调整搜索列表清单

`top300` 剧集中许多配角并非高频角色，需要重建 Bangumi 清单：

- 将剧集拓展到 **top 4000** 番剧的角色
- 在这批番剧角色中取 **top 15000** 个角色即可

**开始之前**：备份既有 Bangumi 结果，尤其是 `characters_ranked.json`。

## Bangumi 调研的需求描述

在仓库根目录 `.env` 中配置 `BANGUMI_API_KEY`。

阅读 [Bangumi API 文档](https://bangumi.github.io/api/) 掌握 API 用法。

目标数据：

- 人气 top 300 的番剧列表
- 人气 top 500 的角色
- （可选）尝试获取人气 top 3000 的角色列表
- 若无法直接拿到 3000 个角色，则从 top 300 剧目中抽取主要角色
- 上述结果取并集

## 角色图片数据集的需求

角色信息已在 `local_data/bangumi/characters_ranked.json`（或当前管线产出的等价文件）中。

- 对每个角色的图片 URL 进行抓取，**两张有效即可**（按 `large` → `medium` → `grid` → `small` 优先级）
- 链接失败支持 **5 次重试**
- 图片保存在 `local_data/` 下，使用**严格、可逆查**的命名体系（便于从角色 ID 定位本地文件）
- 整体抓取可在服务器上跑 **2–3 天**，需设置合理延时，避免对 `bgm.tv` 造成过大压力
- 本地可先抓 **top 30** 个角色验证
- 提供 **HTML** 展示：角色名 + 每角色 1 张图
- 提供 **shell 脚本**，便于在服务器上一键运行批量抓取
