# GenePathway AI：AWS Elastic Beanstalk 内部部署

这个源码包使用以下部署结构：

- AWS Elastic Beanstalk 运行 Flask + Gunicorn。
- Amazon Cognito 负责登录、密码和用户生命周期。
- Cognito 关闭 self-service sign-up，只允许管理员创建用户。
- 应用层再通过 `ALLOWED_EMAILS` 做一次邮箱白名单校验。
- Amazon SES 不是登录系统；只有需要自定义发件人或提高邮件额度时才需要接入。

## 1. 创建 Cognito 内部用户池

在 AWS Console 打开 Amazon Cognito，创建一个 User pool：

1. Sign-in identifier 选择 `Email`。
2. Self-service sign-up 选择关闭，仅允许管理员创建用户。
3. 创建 App client，类型选择传统 server-side web application，并生成 client secret。
4. OAuth flow 只启用 `Authorization code grant`。
5. Scopes 启用 `openid`、`email`、`profile`。
6. 配置 Cognito domain，例如：
   `https://genepathway-team.auth.us-east-1.amazoncognito.com`
7. Allowed callback URL：
   `https://YOUR_APP_DOMAIN/auth/callback`
8. Allowed sign-out URL：
   `https://YOUR_APP_DOMAIN/login`
9. 在 Users 页面由管理员创建 Bingxin 的完整邮箱。不要开启公开注册。

第一次登录时，Cognito 可向该邮箱发送临时密码，并要求用户设置新密码。若使用 Cognito 默认邮件发送能力，初期不需要单独配置 SES。

## 2. 创建 Elastic Beanstalk 环境

1. 创建 `Web server environment`。
2. Platform 选择 Python 3.11 或更高版本。
3. 初始建议选择 Single instance，验证完毕后再决定是否添加负载均衡器。
4. 上传 `GenePathwayAI_AWS_ElasticBeanstalk.zip`。
5. 开启 Enhanced health reporting；本包已把健康检查路径设置为 `/api/status`。
6. 为域名配置 HTTPS。认证 Cookie 在生产模式下只通过 HTTPS 发送。

本应用当前把运行中的分析 session 和 history 保存在实例内存/本地文件中，因此初始配置使用一个 Gunicorn worker。不要直接启用多实例自动扩容，否则不同请求可能落到不同进程或实例。要扩容时，应先把 session、任务状态和历史记录迁移到 Redis、DynamoDB、S3 或数据库。

## 3. 配置环境变量

在 Elastic Beanstalk 的 Environment properties 中配置：

```text
AUTH_ENABLED=true
ACCESS_MODE=team
APP_BASE_URL=https://YOUR_APP_DOMAIN
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_EXAMPLE
COGNITO_CLIENT_ID=YOUR_APP_CLIENT_ID
COGNITO_DOMAIN=https://genepathway-team.auth.us-east-1.amazoncognito.com
ALLOWED_EMAILS=bingxin-full-email@example.com
ADMIN_EMAILS=admin-full-email@example.com
ENTREZ_EMAIL=team-contact@example.com
GPT_MODEL=gpt-5.1
QUOTA_ENABLED=true
QUOTA_BACKEND=dynamodb
QUOTA_TABLE_NAME=GenePathwayAI-Usage
USER_DAILY_JOB_LIMIT=3
MAX_USER_DAILY_JOB_LIMIT=200
GLOBAL_DAILY_JOB_LIMIT=30
MAX_CONCURRENT_JOBS=1
```

以下内容属于 secret，不要写入 ZIP 或 Git：

```text
FLASK_SECRET_KEY=LONG_RANDOM_VALUE
COGNITO_CLIENT_SECRET=YOUR_APP_CLIENT_SECRET
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
```

推荐使用 AWS Secrets Manager 或 Systems Manager Parameter Store，并让 Elastic Beanstalk 将 secret 注入环境变量。`FLASK_SECRET_KEY` 可使用密码管理器生成至少 32 字节的随机值。

如果有多个内部成员，使用逗号分隔邮箱：

```text
ALLOWED_EMAILS=bingxin@example.com,second.member@example.com
```

每位成员同时必须存在于 Cognito 用户池中；仅满足白名单或仅拥有 Cognito 账户都不足以进入应用。

## 4. 公开前配额与登录准备

公开前保持 `ACCESS_MODE=team` 和 Cognito self-service sign-up 关闭。代码已经支持
`ACCESS_MODE=public`，但只有完成配额、用户数据隔离和外部身份提供商验收后才切换。

每日配额使用 DynamoDB 表 `GenePathwayAI-Usage`：

1. Partition key 使用字符串类型 `pk`。
2. 开启 TTL，属性名使用 `expires_at`。
3. EC2 instance profile 需要该表的 `dynamodb:BatchGetItem` 与
   `dynamodb:UpdateItem` 权限。应用调用 `TransactWriteItems` API，但 IAM
   按事务中实际使用的底层 `UpdateItem` 动作授权。
4. 默认限制为每用户 3 次、全站 30 次、同一时间 1 个分析任务。

`ADMIN_EMAILS` 中的用户会在登录后的账户区域看到隐藏的 Admin 入口。管理页可以查看
当天的个人/全站用量，并为 `ALLOWED_EMAILS` 中的用户设置 1–200 次的独立每日上限；
重置后恢复 `USER_DAILY_JOB_LIMIT`。入口隐藏只是界面层，`/admin` 与 `/api/admin/*`
同时有服务端管理员校验。

Google 登录使用 Cognito 的 Google social provider；Microsoft 登录使用 Cognito
OIDC provider。两者都复用当前 `/auth/callback`，外部平台回调地址则是 Cognito
域名下的 `/oauth2/idpresponse`。启用 provider 前必须先在 Google Cloud 和
Microsoft Entra ID 创建应用并取得 Client ID/Secret。

## 5. 部署后的验收

1. 打开应用根路径，应先看到 GenePathway AI 登录页。
2. 点击 `Continue with team account`，应跳转到 Cognito 托管登录页。
3. 使用管理员创建的邮箱登录后，应回到应用首页。
4. 未在 `ALLOWED_EMAILS` 中的 Cognito 用户应被拒绝。
5. `/api/status` 应返回 HTTP 200，未登录时只暴露最小健康状态。
6. 运行一次 demo，再运行一次实际分析，确认 OpenAI 和 g:Profiler 网络访问正常。

## 6. 本地开发

不连接 Cognito时，可临时关闭认证：

```bash
cd web_app
AUTH_ENABLED=false python server.py
```

该设置只用于本机开发。AWS 环境应始终保持 `AUTH_ENABLED=true`。
