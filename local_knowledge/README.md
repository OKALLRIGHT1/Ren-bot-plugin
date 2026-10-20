# 本地第二大脑

用于管理本地知识库。支持指令：learn (扫描文件夹并学习), search (搜索知识库)。参数：指令 ||| 内容(文件夹路径或查询词)

## 怎么用

- 触发词：`knowledge_base`
- 类型：`react`
- 示例：`learn ||| ./docs/my_project`

## 权限

可用：本地桌面、QQ 远程、QQ 主人。
不可用：QQ 他人、群聊未 @。

## 可配置项

- `knowledge_source_dirs`：知识目录。可在 GUI 中手动选择一个或多个知识目录，之后可一键学习这些目录；独立知识库窗口里支持按目录开关。
- `session_kb_enabled`：启用会话知识域。开启后可按会话隔离知识来源标签，后续可扩展为更细粒度知识域。
- `slow_ingest_enabled`：慢速导入模式。批量学习时自动分段暂停，降低远程嵌入 RPM 限频概率。
- `slow_ingest_batch`：每批文件数。处理多少个文件后暂停一次。
- `slow_ingest_sleep_ms`：每批暂停毫秒。批量导入时每批之间暂停多久。
- `adaptive_slow_ingest`：自适应慢速模式。当检测到远程嵌入限频时，自动临时加大暂停时间。
