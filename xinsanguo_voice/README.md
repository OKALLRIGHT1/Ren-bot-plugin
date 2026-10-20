# 新三国语音

识别新三国经典台词关键词并回发对应音频文件。

## 怎么用

- 触发词：`xinsanguo_voice`
- 类型：`direct`
- 别名：`新三国`、`三国语音`、`三国玩梗`
- 示例：`不可能`

## 权限

可用：本地桌面、QQ 远程、QQ 主人、QQ 他人、群聊未 @。

## 可配置项

- `enable_group_only`：仅群聊触发。开启后私聊不会自动匹配台词
- `random_select`：随机选择语音。一条消息匹配多个关键词时只随机发一个
- `session_cooldown_enabled`：启用会话冷却。同一会话触发后进入统一冷却期，避免频繁刷语音
- `session_cooldown_seconds`：会话冷却秒数。同一会话再次自动触发前需要等待的秒数
- `audio_subdir`：音频目录名。相对插件目录的音频子目录，默认 data/sound
- `rules_file`：规则文件名。相对插件目录的规则文件路径
