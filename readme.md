# Cosplay数据收集

我们想做个识别cosplayer在具体cos什么角色的

用于收集不同游戏/番剧的角色数据和cosplay的数据


# TODO

- [ ] 调研bangumi api的使用方式
- [ ] 从番剧名称的角度，搜集番剧的top list
- [ ] 搜集top二次元游戏的list
- [ ] 从番剧，游戏拓展到角色列表 这一步考虑用带search的llm编辑一个prompt来实现
- [ ] （optionl）可以看看什么角色的手办卖得比较火 如果能爬的话
- [ ] 逐个抓取角色的cosplay图像
- [ ] 清理角色和cosplay的所有数据


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

