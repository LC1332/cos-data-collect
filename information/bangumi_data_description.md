# Bangumi 数据文件说明

所有数据存放在 `local_data/bangumi/` 目录下，来源于 Bangumi API (`api.bgm.tv`)。

采集策略：从 Bangumi 排名 Top 4000 番剧出发 → 获取每部番剧的全部角色 → 补充角色详情（收藏数等） → 建立番剧↔角色关联 → 按收藏数截取 Top 15000 角色。

> v1 数据（Top 300 番剧）已备份至 `local_data/bangumi/backup_v1_top300/`

---

## 1. `top_anime.json`

**描述**：Bangumi 排名 Top 4000 的动画条目，按 rank 升序排列。每条包含完整的条目信息（评分、收藏统计、标签、封面图等）。

**记录数**：4000（目标值，实际取决于 Bangumi 数据量）

**关键字段**：`id`, `name`, `name_cn`, `rating.rank`, `rating.score`, `collection`, `tags`, `images`

**Top 5 示例**：

| rank | id | 名称 | 中文名 | 评分 |
|------|----|------|--------|------|
| 1 | 326 | 攻殻機動隊 S.A.C. 2nd GIG | 攻壳机动队 S.A.C. 2nd GIG | 9.2 |
| 2 | 876 | CLANNAD 〜AFTER STORY〜 | CLANNAD 〜AFTER STORY〜 | 9.2 |
| 3 | 25961 | Tom and Jerry | 猫和老鼠 | 9.1 |
| 4 | 253 | カウボーイビバップ | 星际牛仔 | 9.1 |
| 5 | 324 | 攻殻機動隊 STAND ALONE COMPLEX | 攻壳机动队 STAND ALONE COMPLEX | 9.1 |

---

## 2. `characters_ranked.json`

**描述**：从 Top 4000 番剧中提取的所有角色（主角+配角），去重后按 Bangumi 收藏数（`collects`）降序排列，截取 Top 15000。每个角色带有 `relations` 字段记录其所属番剧及角色类型。完整未截断版本见 `characters_ranked_full.json`。

**记录数**：15000（目标值，实际取决于角色总数）

**关键字段**：`id`, `name`, `name_cn`, `collects`, `comments`, `gender`, `summary`, `images`, `relations[].subject_id`, `relations[].subject_name`, `relations[].relation`

**Top 5 示例**：

| 排名 | id | 名称 | 中文名 | 收藏数 | 所属番剧 |
|------|----|------|--------|--------|----------|
| 1 | 12393 | 牧瀬紅莉栖 | 牧濑红莉栖 | 3758 | 命运石之门, 命运石之门 0 |
| 2 | 706 | 戦場ヶ原ひたぎ | 战场原黑仪 | 2608 | 化物语, 物语系列 第二季 等 |
| 3 | 304 | 惣流・アスカ・ラングレー | 惣流·明日香·兰格雷 | 2466 | 新世纪福音战士 等 |
| 4 | 10452 | 初音ミク | 初音未来 | 2391 | 幸运星 OVA |
| 5 | 273 | アルトリア・ペンドラゴン | 阿尔托莉雅·潘德拉贡 | 2120 | Fate/Zero |

---

## 3. `main_characters_ranked.json`

**描述**：`characters_ranked.json` 的子集，仅保留至少在一部番剧中担任"主角"的角色，按收藏数降序排列。

**记录数**：751

**关键字段**：同 `characters_ranked.json`

**Top 5 示例**：

| 排名 | id | 名称 | 中文名 | 收藏数 | 主角所属番剧 |
|------|----|------|--------|--------|--------------|
| 1 | 12393 | 牧瀬紅莉栖 | 牧濑红莉栖 | 3758 | 命运石之门, 命运石之门 0 |
| 2 | 706 | 戦場ヶ原ひたぎ | 战场原黑仪 | 2608 | 化物语, 物语系列 第二季 等 |
| 3 | 304 | 惣流・アスカ・ラングレー | 惣流·明日香·兰格雷 | 2466 | 新世纪福音战士 等 |
| 4 | 273 | アルトリア・ペンドラゴン | 阿尔托莉雅·潘德拉贡 | 2120 | Fate/Zero |
| 5 | 1211 | 忍野忍 | 忍野忍 | 1989 | 物语系列 第二季, 伤物语Ⅲ冷血篇 等 |

---

## 4. `anime_character_map.json`

**描述**：番剧→角色的映射表。每部番剧包含其主角和配角列表（已按角色收藏数排序），用于查看某部番剧有哪些角色。按番剧 rank 升序排列。

**记录数**：4000（目标值，对应采集的番剧数）

**关键字段**：`subject_id`, `name`, `name_cn`, `rank`, `score`, `main_characters[]`, `supporting_characters[]`

**Top 5 示例**：

| rank | subject_id | 中文名 | 主角数 | 配角数 |
|------|------------|--------|--------|--------|
| 1 | 326 | 攻壳机动队 S.A.C. 2nd GIG | 3 | 13 |
| 2 | 876 | CLANNAD 〜AFTER STORY〜 | 2 | 29 |
| 3 | 25961 | 猫和老鼠 | 2 | 16 |
| 4 | 253 | 星际牛仔 | 6 | 91 |
| 5 | 324 | 攻壳机动队 STAND ALONE COMPLEX | 4 | 10 |

---

## 5. `anime_characters_raw.json`

**描述**：从番剧角色接口直接获取的原始数据，未经过详情补充。每个角色记录了其出现在哪些番剧中及角色类型。支持增量抓取（通过 `processed_anime_ids.json` 追踪已处理番剧）。

**记录数**：随采集范围增长

**关键字段**：`id`, `name`, `type`, `images`, `relations[].subject_id`, `relations[].subject_name`, `relations[].relation`

**Top 5 示例**：

| id | 名称 | 出现番剧数 | 首个来源 |
|----|------|------------|----------|
| 84 | 草薙素子 | 9 | 攻壳机动队 S.A.C. 2nd GIG（主角） |
| 3002 | バトー | 9 | 攻壳机动队 S.A.C. 2nd GIG（主角） |
| 3006 | 荒巻大輔 | 9 | 攻壳机动队 S.A.C. 2nd GIG（配角） |
| 3008 | 公安9課 | 8 | 攻壳机动队 S.A.C. 2nd GIG（主角） |
| 3010 | トグサ | 9 | 攻壳机动队 S.A.C. 2nd GIG（配角） |

---

## 6. `characters_enriched.json`

**描述**：在 `anime_characters_raw.json` 基础上，逐个调用角色详情接口补充了 `collects`（收藏数）、`comments`（评论数）、`name_cn`（中文名）、`gender`（性别）、`summary`（简介）等字段。是 `characters_ranked.json` 排序前的中间产物，同时用于断点续传缓存。

**记录数**：随采集范围增长

## 7. `characters_ranked_full.json`

**描述**：截断前的完整角色列表（按收藏数降序）。`characters_ranked.json` 是从此文件截取 Top N 后的结果。

## 8. `processed_anime_ids.json`

**描述**：已完成角色抓取的番剧 ID 列表，用于增量抓取时跳过已处理的番剧。

## 9. `backup_v1_top300/`

**描述**：v1 版本（Top 300 番剧，8416 角色）的完整备份。

**关键字段**：同 `anime_characters_raw.json` + `collects`, `comments`, `name_cn`, `gender`, `summary`

**Top 5 示例**（按原始采集顺序）：

| id | 名称 | 收藏数 | 性别 |
|----|------|--------|------|
| 84 | 草薙素子 | 786 | female |
| 3002 | バトー | 223 | male |
| 3006 | 荒巻大輔 | 48 | male |
| 3008 | 公安9課 | 101 | - |
| 3010 | トグサ | 110 | male |
