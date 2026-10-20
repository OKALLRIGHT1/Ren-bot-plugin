# QQ点歌

通过多平台音乐网关搜索歌曲，默认先搜 QQ 音乐，搜不到再回退网易云，并直接以 QQ 语音形式回发。

## 怎么用

- 触发词：`qq_music`
- 类型：`direct`
- 别名：`点歌`、`qq点歌`、`QQ点歌`、`来首歌`、`放首歌`、`播首歌`、`听歌`
- 示例：`点歌 晴天`

## 权限

可用：QQ 远程、QQ 主人、群聊未 @。
不可用：本地桌面、QQ 他人。

## 可配置项

- `model_queue`：点歌点评模型（按顺序尝试）。从主程序模型中选择聊天用途模型。留空时跟随 default 任务路由。
- `base_url`：API Base URL。接口根地址，例如 https://api.example.com
- `api_key`：API Key。可留空，改用环境变量 QQMUSIC_API_KEY
- `session_cookie`：Session Cookie。如果该网关实际依赖网页登录态，可在这里填完整 Cookie 字符串，例如 sid=...; csrf_token=...
- `default_quality`：默认音质。建议使用 MP3_320 作为 QQ 语音默认格式；如接口支持也可改成 FLAC。
- `provider_order`：搜索源顺序。按顺序尝试的音乐源，逗号分隔。支持 qqmusic, netease, kugou。
- `fallback_to_netease`：QQ 失败回退网易云。当首选 QQ 音乐没搜到候选歌曲时，自动回退到网易云再搜一次。
- `search_page_size`：搜索返回数量。每次搜索从接口拉取的候选歌曲数量。
- `request_timeout_sec`：请求超时(秒)。搜索、取直链、下载音频时的单次请求超时。
- `cache_subdir`：缓存目录。相对项目根目录的缓存子目录，用于暂存下载后的音频。
- `cache_ttl_hours`：缓存保留小时数。超过该时长的旧音频缓存会在下次点歌时自动清理。
- `comment_after_send`：语音后补一句点评。点歌成功并发出 QQ 语音后，再基于歌曲资料和歌词发一条简短评价。
- `comment_defer_until_voice`：先放歌后点评。开启后先把 QQ 语音发出去，再在后台生成并补发点评。
- `comment_dispatch_delay_sec`：点评发送延迟(秒)。语音发出后等待多久再开始补发点评。
- `comment_use_llm`：点评使用 LLM。开启后优先按当前人设生成点评；失败或超时会自动退回本地短评。
- `comment_timeout_sec`：点评超时(秒)。点评生成最多等待多久，超时后立即回退到本地短评。
- `comment_lyric_lines`：点评用歌词行数。生成点评时最多引用多少行歌词进行摘要。
