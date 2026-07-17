# NodeSeek 签到

将 [NodeSeek-Signin](https://github.com/SAGIRIxr/NodeSeek-Signin) 脚本移植为 [MoviePilot](https://github.com/jxxghp/MoviePilot) 插件。原本的环境变量全部改为插件配置页面中**勾选 / 填写**的形式，无需青龙、GitHub Actions 或 Docker 环境变量。

## 目录结构（插件目录）

```
nodeseeksignin/
├── __init__.py             # 插件主体（NodeSeekSignin 类）
├── yescaptcha.py           # YesCaptcha / 2Captcha 验证码（anti-captcha 协议）
└── requirements.txt        # 依赖：curl_cffi
```

## 安装

在 MoviePilot → 设定 → 插件 → 插件仓库，添加本插件库地址
`https://github.com/SAGIRIxr/MoviePilot-Plugins`，然后在插件市场安装 **NodeSeek签到**。
首次启用时 MoviePilot 会自动安装 `requirements.txt` 中的 `curl_cffi`。

## 配置项

| 配置项 | 说明 |
|--------|------|
| 启用插件 | 总开关 |
| 开启通知 | 签到结果通过 MoviePilot 通知渠道推送 |
| 立即运行一次 | 保存后立刻执行一次签到（不做随机延迟） |
| 随机鸡腿奖励 | `NS_RANDOM`。开 = 随机 1~11 个鸡腿，关 = 固定 5 个 |
| 签到时间随机延迟(分钟) | 定时触发后随机延迟 0~N 分钟再签到，0 = 关闭 |
| 使用系统代理 | 所有请求（含签到、登录、验证码 API）走 MoviePilot 配置的代理 |
| 签到周期 | 标准 cron 表达式，默认 `0 8 * * *` |
| 收益统计周期(天) | 统计近 N 天鸡腿收益，默认 30 |
| NS_COOKIE | 论坛 Cookie，多账号用 `&` 或换行分隔 |
| 账号密码 | 每行一个，格式 `用户名----密码`，顺序与 Cookie 一一对应 |
| 验证码服务 | `yescaptcha` 或 `2captcha` |
| API_BASE_URL | 自定义验证码服务节点（如国内中转），留空用官方 |
| CLIENTT_KEY | 验证码服务密钥 |

## 工作方式

- **Cookie 优先**：插件优先用 Cookie 签到，Cookie 有效就一直用、不会重新登录；仅当 Cookie 失效时，才用账号密码通过内置浏览器（CloakBrowser）自动登录刷新出新 Cookie 并写回配置。
- **首次必填 Cookie**：NodeSeek 对机房 IP 有风控，没有可信会话历史时账密登录会被要求邮箱验证码。请首次务必填入一份有效 Cookie（浏览器登录 nodeseek.com 后复制整段）跑通，让本机 IP 成为可信会话，之后账密登录刷新即可绕开邮箱验证。
- 账密登录需配置验证码服务（YesCaptcha 或 2Captcha），并要求 MoviePilot 已准备浏览器仿真环境。

## 使用建议

- **只用 Cookie**：填写 `NS_COOKIE` 即可，最简单，Cookie 失效需手动更新。
- **Cookie + 账密**：同时填写账密与验证码服务密钥，Cookie 失效时自动登录刷新，实现自动维护。

签到结果与近 N 天收益统计可在插件「数据页」查看。
