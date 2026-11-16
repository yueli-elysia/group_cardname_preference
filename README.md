# 群聊昵称优先（group_cardname_preference）

让 bot 在群聊里遇到陌生成员时，优先用**群名片**称呼对方，而不是 QQ 账号昵称；已经熟悉的成员保持原有称呼方式。

## 功能

- 只在群聊生效，私聊完全不受影响。
- 通过 `person_info.interaction_count` 判断陌生成员：
  - 互动次数不超过 `stranger_max_interactions`（默认 `1`）视为陌生；
  - 首次互动时间距今不超过 `new_user_grace_seconds`（默认 1800 秒）也视为陌生，避免新成员连发多条消息后立刻被当成熟人。
- 给陌生成员的消息行追加 `[陌生]` 标记，例如：

  ```text
  昵称:QQ昵称$群名片:群名片 [陌生] [消息ID]： 消息内容
  ```

- 当本轮上下文出现 `[陌生]` 时，把 user prompt 里的称呼规则改为：

  > 消息行里出现 `[陌生]` 标记的成员是你还不熟悉的人，优先使用他的群名片称呼；其他熟悉的成员，仍优先参考用户昵称。

- 没有群名片、群名片与 QQ 昵称相同的成员不会加标记，仍按原规则处理。

## 适用环境

- Neo-MoFox
- 使用 `neo_default_chatter` 作为聊天主控制器
- `min_core_version`: `1.2.0-rc.2`

## 配置

安装后配置位于：

```text
config/plugins/group_cardname_preference/config.toml
```

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用插件 |
| `stranger_max_interactions` | `1` | 互动次数不超过该值时视为陌生 |
| `new_user_grace_seconds` | `1800` | 首次互动后的宽限期，期间仍视为陌生；`0` 表示关闭 |
| `stranger_marker` | `[陌生]` | 消息行中的陌生标记 |
| `prompt_name` | `neo_default_chatter_user_prompt` | 需要修改称呼规则的 user prompt 模板名 |
| `cache_ttl_seconds` | `30` | 互动次数缓存秒数 |

## 数据与隐私

- 插件只读取本地的 `person_info` 表（互动次数、首次互动时间）用于判断熟悉度。
- 不发送任何网络请求，不上传聊天内容。
- 消息行格式化复用框架的 `BaseChatter.format_message_line`，不修改消息本身。

## 已知限制

- 历史消息从数据库恢复时，框架只恢复 `PersonInfo.cardname`（跨群最新值），因此历史消息里的群名片可能不是当前群的名片；当前新消息使用 OneBot 实时群名片，不受影响。
- 插件通过 `neo_default_chatter` 的 `:format_unread_line`、`:build_history_text`、`:fetch_unreads` 事件和系统 `on_prompt_build` 事件工作，不修改核心代码。

## 许可

AGPL-3.0
