# NodeSeek 签到

将 [NodeSeek-Signin](https://github.com/SAGIRIxr/NodeSeek-Signin) 脚本移植为 [MoviePilot](https://github.com/jxxghp/MoviePilot) 插件。原本的环境变量全部改为插件配置页面中**勾选 / 填写**的形式，无需青龙、GitHub Actions 或 Docker 环境变量。

## 目录结构（插件目录）

```
nodeseeksignin/
├── __init__.py             # 插件主体（NodeSeekSignin 类）
├── turnstile_solver.py     # TurnstileSolver（CloudFreed）验证码
├── yescaptcha.py           # YesCaptcha 验证码
└── requirements.txt        # 依赖：curl_cffi
```

## 安装

在 MoviePilot → 设定 → 插件 → 插件仓库，添加本插件库地址
`https://github.com/SAGIRIxr/MoviePilot-Plugins`，然后在插件市场安装 **NodeSeek签到**。
首次启用时 MoviePilot 会自动安装 `requirements.txt` 中的 `curl_cffi`。

## 配置项（原环境变量对照）

| 配置项 | 原环境变量 | 说明 |
|--------|-----------|------|
| 启用插件 | - | 总开关 |
| 开启通知 | - | 签到结果通过 MoviePilot 通知渠道推送 |
| 立即运行一次 | - | 保存后立刻执行一次签到 |
| 随机签到 | `NS_RANDOM` | 开 = 随机鸡腿，关 = 固定 |
| 使用系统代理 | - | 请求走 MoviePilot 配置的代理 |
| 回写刷新Cookie | - | 账密登录拿到新 Cookie 后写回配置 |
| 签到周期 | - | 标准 cron 表达式，默认 `0 8 * * *` |
| 收益统计周期(天) | - | 统计近 N 天鸡腿收益，默认 30 |
| NS_COOKIE | `NS_COOKIE` | 论坛 Cookie，多账号用 `&` 或换行分隔 |
| 账号密码 | `USER/PASS`、`USER1/PASS1`… | 每行一个，格式 `用户名----密码`，顺序与 Cookie 一一对应 |
| 验证码服务 | `SOLVER_TYPE` | `turnstile` 或 `yescaptcha` |
| API_BASE_URL | `API_BASE_URL` | CloudFreed 地址；YesCaptcha 可留空 |
| CLIENTT_KEY | `CLIENTT_KEY` | 验证码服务密钥 |
| NS_IMPERSONATE | `NS_IMPERSONATE` | curl_cffi 首选指纹，默认 `chrome110` |
| 历史记录保留天数 | - | 插件内签到历史保留天数，默认 30 |

> 原脚本中将 Cookie 写回 GitHub Actions 变量 / 青龙面板 / 文件的逻辑，在插件版中改为写回插件自身配置（「回写刷新Cookie」开关控制）。`notify.py` 多渠道通知由 MoviePilot 内置通知体系替代。

## 使用建议

- **只用 Cookie**：填写 `NS_COOKIE` 即可，最简单，Cookie 失效需手动更新。
- **Cookie + 账密**：同时填写账密，Cookie 失效时自动通过验证码服务登录刷新。账密登录必须配置验证码服务（自建 CloudFreed 或购买 YesCaptcha）。

签到结果与近 N 天收益统计可在插件「数据页」查看。
