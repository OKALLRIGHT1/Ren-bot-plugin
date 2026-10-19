# 日报

`plugins/Isuzu_news/` · 类型 `direct` · 触发词 `magic_daily`

生成图片版日报。标题、头图和问候默认跟当前角色走；板块可开关。数据源失败时留空，不再用过期假新闻顶上。

## 调用方式

| 项 | 值 |
| --- | --- |
| 触发词 | `magic_daily` |
| LLM 指令 | `magic_daily` |
| 插件类型 | `direct` |
| 别名 | `/日报`、`/魔法日报` |
| 超时 | 120 秒 |

示例：

```
[CMD: magic_daily | /日报]
```

## 权限

| 渠道 | 允许 |
| --- | --- |
| 本地桌面 | ✅ |
| QQ 远程 | ✅ |
| QQ 主人 | ✅ |
| QQ 他人 | ❌ |
| 群聊未 @ | ✅ |

## 可配置项

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `api_token` | secret | （密钥，存 data/plugin_secrets.db） | ALAPI Token |
| `max_anime_count` | number | 8 | 今日新番数量 |
| `max_news_count` | number | 5 | 新闻数量 |
| `max_hotword_count` | number | 5 | B站热点数量 |
| `max_holiday_count` | number | 4 | 摸鱼日历数量 |
| `render_mode` | choice | image | 渲染模式 |
| `render_dpr` | number | 4 | 渲染清晰度 (DPR) |
| `enable_scheduled_push` | bool | True | 启用定时推送 |
| `scheduled_push_time` | text | 10:00 | 定时推送时间 |
| `scheduled_push_targets` | list | 空 | 定时推送目标会话，例如 `group:123456` |
| `enable_ai_greeting` | bool | True | 问候风格为当前角色时生成短问候 |
| `title` | text | （空） | 报纸名；留空则用「角色名 + 日报」 |
| `title_en` | text | （空） | 英文副标题 |
| `header_image` | text | （空） | 头图；留空用角色徽章 / QQ 头像 |
| `greeting_style` | choice | character | character / custom / off |
| `custom_greeting` | text | （空） | custom 时的文案，可用 `{name}` `{title}` |
| `footer` | text | （空） | 页脚 |
| `sections` | list | 6 项 | 板块顺序：moyu / bili_hot / today_anime / world_news / it_news / hitokoto |
| `output_dir` | text | output/daily_reports | 本地保存目录 |

在 GUI「插件管理」里改，或直接编辑本目录的 `config.json`。

## 运行时

- 会 `asyncio.create_task` 起后台任务。
- 生命周期钩子：`start` 有、`stop` 有。

## 依赖与数据

- 第三方包：`aiohttp`、`jinja2`、`magic_daily`、`playwright`、`xml`、`zhdate`
- 宿主模块：`core`、`modules`、`plugins`、`services`
- 涉及的数据路径字面量：`config.json`、`group_mapping.json`

## 源码

约 1857 行 Python。

---

本节以上由 `dev_scripts/gen_plugin_readme.py` 从 `config.json` 与源码 AST 生成，改完插件请重新运行以免过期。

<!-- KEEP BELOW: 手写补充，重新生成时保留 -->
标题留空时用当前角色名，例如「高松灯日报」。问候默认读角色提示词，不再写死魔法少女口吻。定时推送目标不要填进仓库默认值。
