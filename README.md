# DZZI.AI 自动签到 (GitHub Actions)

支持 [DZZI.AI (New API)](https://api.dzzi.ai/) 每日自动签到，签到奖励 10000–50000 quota (≈ 0.02–0.10 元)。多账号、推送通知、零依赖皆已就绪。

> 已通过实际登录 + 真实签到 API 验证：基于 `QuantumNous/new-api` 框架的 `GET/POST /api/user/checkin`。

## 仓库结构

```
.
├── checkin.py                # 签到主脚本
├── requirements.txt          # 仅依赖 requests
└── .github/workflows/
    └── checkin.yml           # GitHub Actions 定时任务
```

## 快速开始

### 1. Fork 仓库

将本项目 fork 到你自己的 GitHub 账号下。

### 2. 配置 Secrets

进入 `Settings → Secrets and variables → Actions → New repository secret`，添加以下变量：

| Secret 名称 | 必填 | 说明 |
| --- | --- | --- |
| `DZZI_ACCOUNTS` | ✅ | 账号配置，单账号 `user\|password`；多账号每行一个 |
| `NOTIFIER` | ❌ | 推送方式：`feishu` / `serverchan` / `telegram` / `bark` |
| `NOTIFIER_TOKEN` | ❌ | 对应推送方式的凭证 |

#### `DZZI_ACCOUNTS` 格式

**单账号**：
```
123456@qq.com|123456
```

**多账号**（每行一个，或用 `;` 分隔）：
```
123456@qq.com|123456
another@qq.com|anotherPwd
```

也支持 JSON 数组（适合多账号 + 各自 base_url）：
```json
[
  {"username": "a@qq.com", "password": "pwda"},
  {"username": "b@qq.com", "password": "pwdb", "base_url": "https://api.dzzi.ai"}
]
```

### 3. 启用 Workflow

- 进入 `Actions` 页面，启用 workflows（如未启用）。
- 第一次可手动 `Run workflow` 验证。
- 默认 cron: `5 0 * * *` (UTC 00:05 / 北京时间 08:05)，按需修改 `.github/workflows/checkin.yml`。

### 4. 推送方式

| NOTIFIER | NOTIFIER_TOKEN 填写示例 |
| --- | --- |
| `feishu` | `https://open.feishu.cn/open-apis/bot/v2/hook/xxxx` 或直接填 hook key |
| `serverchan` | `SCT2xxxxx` 或完整 `https://sctapi.ftqq.com/xxx.send` |
| `telegram` | `BOT_TOKEN\|CHAT_ID`（用竖线分隔）|
| `bark` | `https://api.day.app/yourkey`（自部署可改域名）|

## 本地运行

```bash
pip install -r requirements.txt
export DZZI_ACCOUNTS='123456@qq.com|123456'
python checkin.py
```

可选：`export NOTIFIER=feishu NOTIFIER_TOKEN=xxx` 同时启用推送。

## 实现要点

- **登录**：`POST /api/user/login?turnstile=` (turnstile 可为空)，得到 `session` cookie。
- **认证**：`GET/POST /api/user/checkin` 需携带 `New-Api-User: <id>` 头（取自登录响应中的 `data.id`）。
- **幂等**：脚本先查询 `GET /api/user/checkin`，已签到则跳过，避免重复。
- **额度换算**：new-api 内 `1 元 = 500000 quota`，脚本按此输出元/天。
- **来源参考**：[QuantumNous/new-api controller/checkin.go](https://github.com/QuantumNous/new-api/blob/main/controller/checkin.go)。

## 常见问题

- **登录失败 Unauthorized**：密码错误，或账号被封禁。
- **今日已签到**：说明今天已成功执行过，脚本已自动跳过。
- **网络超时**：GitHub Actions 偶发，重试即可。
- **想换时间**：修改 `.github/workflows/checkin.yml` 的 `cron` 字段，时区为 UTC。

## License

MIT
