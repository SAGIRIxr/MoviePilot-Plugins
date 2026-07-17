# Discord消息转发

轮询 Discord 频道新消息，通过 MoviePilot 系统通知渠道转发到微信 / Telegram 等，支持关键词过滤与兑换码正则提取。典型场景：把游戏官方 Discord 的礼包码公告（如寒霜启示录 WOS giftcode 频道）转发到微信。

## 功能

- 多频道监听：每行一个频道，支持 `频道ID#备注名` 格式
- 通过 Discord REST API 轮询（Bot Token），无需常驻 WebSocket，间隔可配
- 首次运行只记录基线，不会把历史消息刷一遍
- 消息正文、Embed（标题/描述/字段）、附件链接都会提取转发
- 可选关键词过滤：命中任一关键词才转发
- 可选兑换码正则：命中的兑换码在通知里单独列出，并记录在历史页
- 走 MoviePilot 系统通知渠道，通知类型可选；支持系统代理
- 插件详情页展示转发历史

## 准备工作

1. **创建 Bot**：打开 [Discord 开发者平台](https://discord.com/developers/applications) → New Application → 左侧 Bot：
   - `Reset Token` 获取 Bot Token（只显示一次，保存好）
   - 开启 **MESSAGE CONTENT INTENT**（否则拉不到消息正文）
2. **把 Bot 拉进自己的服务器**：左侧 OAuth2 → URL Generator → Scopes 勾 `bot` → Bot Permissions 勾 `View Channels`、`Read Message History` → 打开生成的 URL，选择自己的服务器授权。
3. **获取频道 ID**：Discord 客户端 设置 → 高级 → 开启「开发者模式」，右键目标频道 → 复制频道 ID。
4. 想监听**别人服务器**的频道（无法拉 Bot）：如果对方是公告频道（有 Follow/关注 按钮），先把它关注到自己服务器的某个频道，再监听自己这个频道即可。

## 配置说明

| 配置项 | 说明 |
|--------|------|
| Bot Token | Discord 开发者平台创建的 Bot Token |
| 监听频道 | 每行一个，`频道ID` 或 `频道ID#备注名` |
| 轮询间隔 | 默认 5 分钟 |
| 使用系统代理 | 国内环境必须开启（走 MP 设定里的代理） |
| 通知类型 | 转发消息使用的 MP 通知类型，默认「插件」 |
| 关键词过滤 | 逗号分隔，留空转发全部 |
| 兑换码提取正则 | 留空不提取，如 `[A-Za-z0-9]{6,20}` |

## 常见问题

- **HTTP 401**：Token 错误或已重置。
- **HTTP 403**：Bot 不在该服务器，或没有「查看频道 / 阅读消息历史」权限。
- **消息正文是空的**：没开 MESSAGE CONTENT INTENT。
- **收不到通知**：先确认 MP 设定 → 通知 渠道正常，且所选「通知类型」在通知渠道的消息类型开关里是打开的。
