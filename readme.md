# Cosplay数据收集

我们想做个识别cosplayer在具体cos什么角色的

用于收集不同游戏/番剧的角色数据和cosplay的数据


# TODO

- [x] 调研bangumi api的使用方式
- [x] 搜集top番剧对应角色的列表
- [x] 获取角色的图片数据集
- [ ] (optional) 增补游戏列表和游戏数据
- [ ] （optionl）可以看看什么角色的手办卖得比较火 如果能爬的话
- [ ] 逐个抓取角色的cosplay图像
- [ ] 清理角色和cosplay的所有数据


# 角色图片数据集的需求

注意到我们已经在local_data/bangumi/characters_ranked.json 中间获取了角色的信息

这里我希望对每个图片的image进行抓取
抓两张有效的就可以（按照从large medium grid small的优先级）
链接访问失败可以支持5次重试

保存下来的图片在local_data里面搞个文件夹 要有严格一点的命名体系方便我顺着角色仍然能找到local的图片

我整体的抓取程序会放在服务器上运行
我希望整体的抓取可以放在2-3天，帮我设置合理的延时避免冲爆 bgm.tv的服务器

在本地你帮我抓top 30个角色就可以了

另外再做个html可以展示角色图片和角色名（每个角色1张）

然后做个sh脚本方便我直接在服务器上运行抓取

# bangumi调研的需求描述

我已经在.env中配置了 BANGUMI_API_KEY

阅读 https://bangumi.github.io/api/  学会api的使用

我想找的是 

- 人气top 300的番剧列表
- 人气top500的角色
- (opt) 尝试能不能获取人气top 3000的角色列表
- 如果不能获取3000个角色，尝试从 top300剧目中获取主要角色
- 两者取并集

# protocol

- 源代码在 src/ 目录，子功能建立子文件夹（如 src/convert_taobao_mm/）
- 较大的数据（若果有新产生的）放 local_data/（加入到 gitignore）
- 总结性信息放 information/ 文件夹
- 这个项目可以先不用uv进行环境管理 之后我移到服务器上的时候再搞uv
- 如果项目有一些疑问，可以累积一些问题之后暂停你的运行，在readme的to_be_owner_check中增- 加问题留owner确认

