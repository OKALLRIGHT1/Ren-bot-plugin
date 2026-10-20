# QQ生图

仅在 QQ 中用固定斜杠命令触发生图。模型唯一来自「模型与路由」：先给模型勾选画图用途，再在任务路由「画图」里手动选择要用的模型与顺序（不会自动全选）。

## 怎么用

- 触发词：`qq生图`
- 类型：`direct`
- 别名：`/画图`、`/画画`
- 示例：`/画图 绘制一个丰川祥子在雨后的街道`

## 权限

可用：QQ 远程、QQ 主人。
不可用：本地桌面、QQ 他人、群聊未 @。

## 可配置项

- `model_queue`：画图模型（按顺序尝试）。从模型管理里筛选「画图/图生图」用途的模型，手动加入右侧执行链。上方优先，失败才试下面的。连接信息仍来自模型与路由。
- `size_value`：默认尺寸。例如 1024x1024。模型侧也可单独覆盖。
- `quality`：质量。可选，兼容 OpenAI 风格接口时可填 standard / hd；留空则不传。
- `style`：风格。可选，兼容 OpenAI 风格接口时可填 vivid / natural；留空则不传。
- `negative_prompt`：默认负面提示词。可选，部分兼容接口支持 negative_prompt。
- `extra_body_json`：额外请求体(JSON)。会合并进最终请求体；chat 模式下适合补 stream、modalities 等字段。
- `request_timeout_sec`：请求超时(秒)。单次生图请求 HTTP 超时。慢速上游可调到 300 或 360；超时后会试队列里下一个模型。
- `caption_template`：回发说明模板。{prompt} 会替换成这次的绘图提示词；{provider} 会替换成实际成功的模型 ID。
- `image_to_image_enabled`：启用图生图。当 QQ 消息里同时带图片时，把你发的图片全部作为参考图一起传给后端（可多张）。
- `max_input_images`：最多参考图数量。消息里带了几张就传几张，但不会超过这个上限。
- `input_image_field`：输入图字段名。JSON 生图接口里放输入图的字段名，常见可尝试 image、image_base64、init_image。
- `input_image_format`：输入图格式。可填 data_url 或 base64；大多数兼容 chat/multimodal 的接口更适合 data_url。
- `include_chat_image_part`：附带聊天图片片段。会把输入图同时放进 messages[].content 里，适合多模态 chat/completions 风格接口。
- `debug_logging`：调试日志。开启后会在日志里记录模型队列、请求地址以及返回摘要。
