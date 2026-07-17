# MoviePilot-Plugins

SAGIRIxr 的 [MoviePilot](https://github.com/jxxghp/MoviePilot) 第三方插件库。

本库 **fork 自官方 [jxxghp/MoviePilot-Plugins](https://github.com/jxxghp/MoviePilot-Plugins)**，沿用官方仓库的目录排版（`plugins/`、`plugins.v2/`、`icons/`、`docs/`、发布工作流等），删除了官方自带的其它插件，仅保留本人开发的插件，便于后续持续新增。

## 插件列表

| 插件 | 目录 | 说明 |
|------|------|------|
| NodeSeek签到 | [`plugins.v2/nodeseeksignin`](plugins.v2/nodeseeksignin) | NodeSeek 论坛自动签到：多账号 Cookie / 账密登录、随机签到、收益统计、通知。详见插件目录内 README。 |
| Discord消息转发 | [`plugins.v2/discordmsgforward`](plugins.v2/discordmsgforward) | 将 Discord 频道新消息按规则转发到指定通知渠道：Vue 卡片式规则管理，每条规则独立配置频道、渠道、过滤、模板与免打扰时段。详见插件目录内 README。 |

## 安装

MoviePilot → 设定 → 插件 → 插件仓库，添加本库地址：

```
https://github.com/SAGIRIxr/MoviePilot-Plugins
```

然后在「插件市场」中找到对应插件安装即可。

## 目录结构

```
MoviePilot-Plugins/
├── plugins/                # V1 插件目录（暂空）
├── plugins.v2/             # V2 插件目录
│   ├── nodeseeksignin/     # NodeSeek 签到
│   └── discordmsgforward/  # Discord 消息转发
├── icons/                  # 插件图标资源（沿用官方，可复用）
├── docs/                   # 官方插件开发文档（保留供参考）
├── package.json            # V1 插件索引（暂空）
├── package.v2.json         # V2 插件索引
└── .github/workflows/      # 发布工作流（沿用官方）
```

## 开发新插件

1. 在 `plugins.v2/<插件类名小写>/__init__.py` 编写插件主类（继承 `_PluginBase`），目录名必须为插件类名的小写。
2. 图标优先复用 `icons/` 下已有图标，或在元数据中使用完整图片 URL。
3. 在 `package.v2.json` 末尾追加一条插件元数据，其中 `version` 必须与插件类的 `plugin_version` 保持一致。
4. 额外依赖写在该插件目录下的 `requirements.txt`，MoviePilot 安装插件时会自动安装。

更多细节参考官方文档：
- [docs/Repository_Guide.md](docs/Repository_Guide.md) — 仓库指南
- [docs/V2_Plugin_Development.md](docs/V2_Plugin_Development.md) — V2 插件开发指南
- [docs/FAQ.md](docs/FAQ.md) — 常见问题索引

## 致谢

插件框架、开发文档与图标资源均来自官方 [MoviePilot-Plugins](https://github.com/jxxghp/MoviePilot-Plugins)。
