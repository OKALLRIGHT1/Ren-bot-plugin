# 萌娘百科查询

查询萌娘百科词条、角色、作品、术语，并返回主词条与相关语境。

## 怎么用

- 触发词：`moegirl_wiki`
- 类型：`delegate`
- 别名：`萌百`、`萌娘百科`、`moegirl`、`查萌百`、`萌娘百科查询`
- 示例：`初音未来是谁`

## 权限

可用：本地桌面、QQ 远程、QQ 主人、QQ 他人。
不可用：群聊未 @。

## 可配置项

- `timeout_seconds`：请求超时(秒)。调用萌娘百科 API 的超时时间
- `cache_ttl_seconds`：缓存秒数。同类查询缓存时长
- `prefer_exact_title`：优先精确标题。优先把精确标题命中的词条视为可信主词条
- `prefer_generator_search`：优先 generator 搜索。优先使用 generator=search，失败再回退 opensearch
- `max_candidates`：候选词条上限。歧义词返回的候选数量上限
- `cookie_string`：萌娘百科 Cookie。可选，默认匿名访问
