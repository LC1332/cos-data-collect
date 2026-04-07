# Cosplay数据收集

我们想做个识别cosplayer在具体cos什么角色的

用于收集不同游戏/番剧的角色数据和cosplay的数据


# TODO

- [x] 调研bangumi api的使用方式
- [x] 搜集top番剧对应角色的列表
- [x] 获取角色的图片数据集
- [ ] (optional) 增补游戏列表和游戏数据
- [ ] （optionl）可以看看什么角色的手办卖得比较火 如果能爬的话
- [x] 建立动漫 & 人物名称简写的prompt和get_response
- [x] 使用 人物名称 cosplay 动漫简写 作为搜索词，连接bing_donwloader
- [x] 增加一个VLM判断哪几个是真的这个角色cosplay的，如果都判断不是，在下载过程中再增加一次query
- [x] 调整搜索列表清单 扩展至top 4000番剧，取角色top 15000（支持增量抓取）
- [x] 建立一个简单的VLM naive识别的benchmark
- [ ] 逐个抓取角色的cosplay图像
- [ ] 清理角色和cosplay的所有数据

# 建立generated图-角色图-group图的对比

在local_data/group中我放了我生成的5张角色的图
角色原图在local_data/bangumi/character_images
生成的cos图在local_data/generated_images

帮我生成一个紧凑一点的页面（一行显示两组） 依次显示 cos图 角色图和合影
（图片不要crop 保aspect缩放）

# 建立角色图 generated图和真实cos图的对比

在local_data/generated_images 中 我用角色id放了角色用z-image模型生成的角色图
帮我做个页面，可以对比 角色原图 - 生成图 和 cosplay图（如有，需要经过了gemini认证）
注意保持图片不要裁切保证aspect缩放

# 通过model_scope尝试qwen-image-edit

在src/char2cos中，我放置了一个可参考的app.py

注意我在env中增加了 MODEL_SCOPE_KEY

我这里希望编写一段新的代码，

借助model_scope的api，使用qwen-image-edit-2511模型

把图片
local_data/bangumi/character_images/1211_medium.jpg

通过prompt

“把图片转化为物语系列的忍野忍的真人cosplay, 年轻, 大学生, photorealistic”

试图转化为cosplay照片

注意model scope的接口可能发生了一些该拜年


# 一个简易的VLM识别的benchmark

这里我们发现VLM本来就具有一定的视觉识别的能力

因为我后台实际上还在抓取角色的名单，我希望你根据现存的
角色结果，整理出一个临时的characters_ranked.json

然后这里我希望针对rank = 100, 200 ,... 1000 的角色

使用管线去寻找他们的cos图，
如果100i的找不到，就顺位找100i+1的（至多尝试到100i+4）

每个角色找到一个cos图就可以了
然后相当于凑出10个不同角色的测试样本

然后我要用思维力链（类似src/brief_name/get_brief_names.py中的方式）
去询问VLM 当前图片中的人物在cos什么番剧/游戏中的什么角色， 分别要求下面的字段

- caption 先描述图片中的人物特点、职业等详细信息
- analysis 分析图片中的人物应该是cos什么番剧的什么角色
- character_name 输出cos角色的名字
- bangumi_name 输出番剧的名字

注意我在.env也增加了zhipu的api key，
测试通过 `.env` 配置的 Gemini / OpenAI 等带视觉能力的模型的结果
并且额外也测试一下
至少包括
gemini-3-flash
gpt-5-mini
GLM-4.6V-FlashX
claude的haiku

# 模块说明（分功能需求）

各子功能的详细需求与说明见对应目录：

| 目录 | 说明 |
|------|------|
| [src/bangumi/readme.md](src/bangumi/readme.md) | Bangumi API 调研、清单调整（top 4000 / 角色 top 15000）、角色参考图抓取与服务器脚本 |
| [src/brief_name/readme.md](src/brief_name/readme.md) | 用 LLM 获取角色/番剧简称、缓存与实验输出 |
| [src/cosplay_search/readme.md](src/cosplay_search/readme.md) | Bing 类下载、搜索词格式、批量与 HTML 展示 |
| [src/cosplay_analysis/readme.md](src/cosplay_analysis/readme.md) | Gemini VLM 拼图鉴定、二次搜索 pipeline、以角色 ID 存储 |
| [src/vlm_benchmark/readme.md](src/vlm_benchmark/readme.md) | VLM naive 识别 benchmark，多模型对比测试 |

# protocol

- 源代码在 src/ 目录，子功能建立子文件夹（如 src/convert_taobao_mm/）
- 较大的数据（若果有新产生的）放 local_data/（加入到 gitignore）
- 总结性信息放 information/ 文件夹
- 这个项目可以先不用uv进行环境管理 之后我移到服务器上的时候再搞uv
- 如果项目有一些疑问，可以累积一些问题之后暂停你的运行，在readme的to_be_owner_check中增- 加问题留owner确认
