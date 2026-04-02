# Cosplay 结果分析（VLM）

本目录负责对搜索返回的 coser 图片做视觉模型鉴定，判断是否为目标角色的 cosplay。

## 需求说明

调用 **Gemini**（优先 **gemini-3-flash**），在 `.env` 中配置密钥与 Gemini 端点变量，约定与 `vlm_client.py` 相同，对返回的至多 5 张图做分析。

### 拼图与标注

- 将**角色原图**与**至多 5 张**搜索结果拼成 **2 行 3 列** 的网格图
- 原图区域标注：`Original_Character`
- 5 张图在标题位置依次标为：`pic_A` … `pic_E`
- 图片需**等比缩放**，不要 crop

### Prompt 模板

```
请帮助我判断每个pics是否是对 Original_Character 的cosplay

我正在寻找 {番剧名称} 中 {角色名称} 的cosplay

在左上角我给出了这个角色的原图，并且之后给出了一些搜索结果

以JSON形式返回你的分析和结果，并包含以下所有字段
- analysis_if_cosplay_image 分析每张图是否是真实风格的cosplay图片，
- analysis_if_correct_character 分析每张图是否相对正确的表达了需要cos的角色，还是错误命中了番剧中的其他无关角色等等。注意一个角色可能在剧中有多套衣服的设定，不一定完全和original-character的服装相同
- if_A_correct 如果A图片是正确的cos图片，返回"true"，不然是"false"
...
- if_E_correct 如果E图片是正确的cos图片，返回"true"，不然是"false"

{图片}
```

### Pipeline

1. 获取 **brief 名称**（简称）
2. 搜索 5 张图
3. **VLM 验证**
4. 若**全部未通过**：再用无 brief 的 `"{原角色名} {原剧名} cosplay coser"` 再搜 5 张并再鉴定
5. 鉴定结果以 **JSON** 持久化

### 数据与脚本

- 角色存储以 **ID** 为主键，不要仅以搜索词标识
- 用 **top 5** 角色跑通端到端测试
- 同步更新 `download_cosplay` 相关脚本（名称以仓库内实际脚本为准）
