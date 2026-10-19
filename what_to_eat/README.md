# 今天吃什么

`plugins/what_to_eat/` · 类型 `direct` · 触发词 `what_to_eat`

仅响应斜杠命令，支持附图推荐、查做法，以及 /吃什么十连 这类拼图抽卡。

## 调用方式

| 项 | 值 |
| --- | --- |
| 触发词 | `what_to_eat` |
| LLM 指令 | `what_to_eat` |
| 插件类型 | `direct` |
| 别名 | `/吃什么`、`/今天吃什么`、`/中午吃什么`、`/晚上吃什么`、`/不知道吃什么`、`/做点什么吃的`、`/做法` |
| 超时 | 3 秒 |

示例：

```
[CMD: what_to_eat | /今天吃什么 / 西红柿炒鸡蛋怎么做 / 做点什么吃的 / 吃什么十连]
```

## 权限

| 渠道 | 允许 |
| --- | --- |
| 本地桌面 | ✅ |
| QQ 远程 | ✅ |
| QQ 主人 | ✅ |
| QQ 他人 | ✅ |
| 群聊未 @ | ✅ |

## 可配置项

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `rate_limit_enabled` | bool | True | 启用频率限制 |
| `rate_limit_max` | number | 3 | 时间窗最大触发次数 |
| `rate_limit_window_seconds` | number | 60 | 频率限制时间窗(秒) |
| `echo_cooldown_enabled` | bool | True | 启用复读冷却 |
| `echo_cooldown_seconds` | number | 15 | 复读冷却秒数 |
| `session_cooldown_enabled` | bool | True | 启用会话冷却 |
| `session_cooldown_seconds` | number | 600 | 会话冷却秒数 |
| `time_awareness_enabled` | bool | True | 启用时间感知 |
| `breakfast_end_hour` | number | 10 | 早餐截止小时 |
| `lunch_end_hour` | number | 14 | 午餐截止小时 |
| `dinner_end_hour` | number | 21 | 晚餐截止小时 |
| `prefer_homestyle` | bool | True | 家常优先 |
| `avoid_non_homestyle_for_eat` | bool | True | 避开偏商用菜 |
| `prefer_complete_recipe` | bool | True | 优先完整菜谱 |

在 GUI「插件管理」里改，或直接编辑本目录的 `config.json`。

## 动作

取自源码里的 action/alias 映射表：

`cook_suggestion` `recipe_lookup`

## 依赖与数据

- 第三方包：`PIL`

## 源码

约 1587 行 Python。

---

本节以上由 `dev_scripts/gen_plugin_readme.py` 从 `config.json` 与源码 AST 生成，改完插件请重新运行以免过期。

<!-- KEEP BELOW: 手写补充，重新生成时保留 -->
