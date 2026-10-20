# 系统运维

系统监控与控制中枢。支持：check / cpu / memory / disk / temperature / gpu / all / start / stop / status / set_volume / mute / set_brightness / lock_screen。

## 怎么用

- 触发词：`monitor`
- 类型：`react`
- 别名：`硬件`、`监控`、`状态`、`cpu`、`memory`、`内存`、`温度`、`temperature`、`sys`、`check`、`检查`、`音量` 等 15 个
- 示例：`set_volume ||| +20`

## 权限

可用：本地桌面、QQ 远程、QQ 主人。
不可用：QQ 他人、群聊未 @。

## 可配置项

- `cpu_threshold`：CPU使用率阈值 (%)。当CPU使用率超过此值时发出警告
- `memory_threshold`：内存使用率阈值 (%)。当内存使用率超过此值时发出警告
- `disk_threshold`：磁盘使用率阈值 (%)。当磁盘使用率超过此值时发出警告
- `cpu_temp_threshold`：CPU温度阈值 (℃)。当CPU温度超过此值时发出警告
- `gpu_threshold`：GPU使用率阈值 (%)。当GPU使用率超过此值时发出警告
- `gpu_temp_threshold`：GPU温度阈值 (℃)。当GPU温度超过此值时发出警告
- `check_interval`：检查间隔 (秒)。后台监控的检查间隔时间
