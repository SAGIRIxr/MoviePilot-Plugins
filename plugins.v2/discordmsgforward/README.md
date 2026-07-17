# Discord消息转发

将 Discord 频道新消息按**规则**转发到 MoviePilot 的指定通知渠道（微信 / Telegram / Slack 等）。v4 起采用 Vue 卡片界面：一条规则一张卡片，独立配置、独立启停。

典型场景：游戏官方公告/礼包码频道转发到微信、社区重要通知汇总、只转发特定 Bot 的推送等。

## 三步上手

1. 全局设置填 **Bot Token**，保存 → 插件自动拉取 Bot 可见的频道列表
2. **添加规则**：起个名字 → 下拉勾选监听频道 → 勾选转发渠道（留空 = 全部渠道）
3. 打开「启用插件」保存即可；详情页可「立即检查」验证

## 界面

- **配置页**：全局设置（Token / 代理 / 轮询间隔 / 通知类型 / 失败告警）+ 规则卡片区（添加 / 编辑 / 删除 / 启停）
- **规则编辑弹窗**：监听频道、转发渠道、消息聚合、图片转发、免打扰时段；过滤规则（关键词 / 屏蔽词 / 作者白黑名单）和高级选项（提取正则 / 消息模板）折叠收纳
- **详情页**：运行状态（规则数 / 失败次数 / 暂存数）、立即检查、转发历史表、清空历史

## 功能

- 规则化转发：每条规则独立的频道、渠道、过滤、模板、免打扰配置；同一频道被多条规则监听时只拉取一次消息
- 过滤链：作者白名单 → 作者黑名单 → 屏蔽词 → 关键词白名单
- 图片转发、消息聚合、通知跳转链接（直达 Discord 原消息）
- 免打扰时段（支持跨零点）：时段内暂存，结束后按规则+频道汇总推送
- 内容提取正则（如礼包码），命中内容单独列出，模板变量 `{codes}`
- 消息模板变量：`{channel}` `{author}` `{content}` `{codes}` `{time}` `{count}`
- 连续 3 次轮询全部失败推送告警，恢复自动重置
- 远程命令 `/discord_check` 手动触发；首次监听只记录基线不刷历史消息

## Bot 准备

1. [Discord 开发者平台](https://discord.com/developers/applications) → New Application → Bot：
   - `Reset Token` 获取 Token（只显示一次）
   - 开启 **MESSAGE CONTENT INTENT**（否则消息正文为空）
2. OAuth2 → URL Generator → Scopes 勾 `bot`，权限勾 `View Channels`、`Read Message History` → 打开 URL 授权进自己的服务器
3. 想转发**别人服务器**的频道（无法拉 Bot）：若对方是公告频道（有 Follow/关注 按钮），先关注到自己服务器的频道，再监听自己这个频道

## 开发

前端源码在 [`frontend/`](frontend/)（Vue 3 + Vuetify + Vite 模块联邦）：

```bash
cd frontend
npm install
npm run build
# 将 dist/assets 下的 remoteEntry.js、__federation_*、_plugin-vue_export-helper-* 复制到 ../dist/assets/
```

## 常见问题

- **频道下拉是空的**：先填 Token 保存，等几秒后点「刷新频道列表」；仍为空看日志（多为代理不通）。
- **HTTP 401**：Token 错误或已重置。
- **HTTP 403**：Bot 不在该服务器，或没有「查看频道 / 阅读消息历史」权限。
- **消息正文是空的**：没开 MESSAGE CONTENT INTENT。
- **收不到通知**：确认 设定→通知 渠道正常，且全局设置所选「通知类型」在目标渠道的消息类型开关里已打开。
- **配置页白屏**：需要 MoviePilot v2.12+（Vue 联邦插件支持），请升级 MP 后重装插件。
