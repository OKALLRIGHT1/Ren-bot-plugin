# 今天吃什么

仅响应斜杠命令，支持附图推荐、查做法，以及 /吃什么十连 这类拼图抽卡。

## 怎么用

- 触发词：`what_to_eat`
- 类型：`direct`
- 别名：`/吃什么`、`/今天吃什么`、`/中午吃什么`、`/晚上吃什么`、`/不知道吃什么`、`/做点什么吃的`、`/做法`
- 示例：`/今天吃什么 / 西红柿炒鸡蛋怎么做 / 做点什么吃的 / 吃什么十连`

## 权限

可用：本地桌面、QQ 远程、QQ 主人、QQ 他人、群聊未 @。

## 可配置项

- `rate_limit_enabled`：启用频率限制。避免连续多次触发时刷屏
- `rate_limit_max`：时间窗最大触发次数。超过后强制推荐食物
- `rate_limit_window_seconds`：频率限制时间窗(秒)。统计触发次数的时间窗
- `echo_cooldown_enabled`：启用复读冷却。复读后短时间内强制推荐食物
- `echo_cooldown_seconds`：复读冷却秒数。复读后的冷却时间
- `session_cooldown_enabled`：启用会话冷却。仅对“吃什么”类纯推荐生效，避免同一会话频繁刷屏
- `session_cooldown_seconds`：会话冷却秒数。同一会话内再次触发前需要等待的秒数
- `time_awareness_enabled`：启用时间感知。未明确说早餐/午餐/晚餐时，按当前时间偏向推荐对应餐段
- `breakfast_end_hour`：早餐截止小时。小于这个小时优先按早餐推荐
- `lunch_end_hour`：午餐截止小时。小于这个小时优先按午餐推荐
- `dinner_end_hour`：晚餐截止小时。小于这个小时优先按晚餐推荐
- `prefer_homestyle`：家常优先。默认优先推荐更像家常菜的菜谱
- `avoid_non_homestyle_for_eat`：避开偏商用菜。在“吃什么”推荐里尽量避开配方料、饮品和明显偏商用品项
- `prefer_complete_recipe`：优先完整菜谱。优先步骤和配料更完整的菜谱来源
