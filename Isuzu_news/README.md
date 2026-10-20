# 日报

生成图片版日报。标题、头图和问候默认跟当前角色走，板块可开关。

## 怎么用

- 触发词：`magic_daily`
- 类型：`direct`
- 别名：`/日报`、`/魔法日报`
- 示例：`/日报`

## 权限

可用：本地桌面、QQ 远程、QQ 主人、群聊未 @。
不可用：QQ 他人。

## 可配置项

- `api_token`：ALAPI Token。用于节假日、今日一言、早报 API。留空则这些板块可能没有内容。
- `max_anime_count`：今日新番数量。建议 4-8。
- `max_news_count`：新闻数量。世界新闻 / IT资讯各自的最大条数，建议 5-10。
- `max_hotword_count`：B站热点数量。建议 4-8。
- `max_holiday_count`：摸鱼日历数量。建议 3-5。
- `render_mode`：渲染模式。image=图片模式（Playwright），text=文字模式（无图片依赖）。
- `render_dpr`：渲染清晰度 (DPR)。越大越清晰但更慢，建议 3-6。
- `enable_scheduled_push`：启用定时推送。启用后会在指定时间推送日报到目标会话。
- `scheduled_push_time`：定时推送时间。HH:MM 24小时制，例如 08:00。
- `scheduled_push_targets`：定时推送目标会话。填 session_id，例如 group:123456 或 private:123456。仅填数字时默认按 group 处理。
- `enable_ai_greeting`：启用 AI 问候语。问候风格为「当前角色」时，用当前模型生成一句短问候；失败回退到带角色名的固定句。
- `title`：日报标题。报纸名。留空则用「角色名 + 日报」。
- `title_en`：英文副标题。标题下方的英文行。留空则用 DAILY REPORT。
- `header_image`：头图路径。本地图片。留空则用当前角色徽章 / QQ 头像。
- `greeting_style`：问候风格。character=当前角色口吻，custom=自定义文案，off=不配问候。
- `custom_greeting`：自定义问候。问候风格为 custom 时使用。可用 {name}、{title}。
- `footer`：页脚。图片底部一行小字。留空则用英文副标题。
- `sections`：板块顺序。可选：moyu、bili_hot、today_anime、world_news、it_news、hitokoto。未列出的不显示。
- `output_dir`：本地保存目录。本地触发时保存图片的目录（相对路径基于项目根目录）。
