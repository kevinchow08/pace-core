# pace-core · CLAUDE.md

## 项目简介

PaceCoach 后端。轮询 COROS 手表数据，自动触发 LLM 生成教练点评（练后点评、今日晨报、伤病预警、周报），通过推送通知发到手机。Phase 1 单用户已完成，Phase 2 做多用户 + Expo App + 支付。

## 协作约定

**学习优先**：这是 Kevin 的第二个全栈项目，目标是实践学习和能力建设，不是快速产品化。

- 解释架构决策背后的"为什么"，不只是"怎么做"
- 终端命令列出来让用户自己跑，不要自动执行安装/初始化命令
- 遇到多种方案时，说清楚 tradeoff，让用户自己选
- **动手前先说方案**：描述打算怎么做，Kevin 确认方向后再实现，不一次性堆满细节
- Kevin 来做判断和决策，Claude 负责实现；语法细节不深究，业务和工程判断必须 figure out

## 技术方案选型约定

Phase 2 涉及较多技术选型（Auth、队列、支付、缓存等），统一遵循：

1. **主流 + 适合当前场景**：不追求大厂方案，追求正确的工程判断。够用且业内认可（如 Celery 而不是 Kafka，JWT 而不是复杂 Session）
2. **出方案先说 why**：动手前说清楚"业内怎么做、为什么、有什么 tradeoff"，Kevin 确认后再实现
3. **能力建设优先**：每个技术点引入都要对应技能地图里的真实能力项，过度设计直接否掉
4. **可以质疑**：方案有更简单替代或明显过度设计时直接提出，Claude 给出判断依据

## 项目结构

```
pace-core/
├── coros_lib/          # vendor 自 cygnusb/coros-mcp（MIT），只保留取数函数
├── src/
│   ├── config.py       # 读 .env / .env.local，所有配置集中在这里（pydantic-settings）
│   ├── coros_client.py # 薄封装 coros_lib，异步工具函数
│   ├── analyzer.py     # LLM 分析：练后点评 / 晨报 / 伤病预警 / 周报
│   ├── notifier.py     # push()，Phase 1 走 Ntfy，Phase 2 换 Expo Push 只改这一个文件
│   ├── store.py        # PostgreSQL 去重 + 各类 Log（asyncpg + SQLAlchemy async）
│   ├── jobs.py         # 四个定时 job：on_new_activity / morning_report / injury_risk_check / weekly_report
│   └── risk.py         # 伤病风险信号评估逻辑
├── api/
│   ├── main.py         # FastAPI 入口，lifespan 启动 AsyncIOScheduler
│   └── routes/         # health / jobs 路由
├── alembic/            # 数据库迁移（alembic upgrade head）
├── main.py             # 调试入口：--once/--morning/--risk/--weekly 手动触发
├── docker-compose.yml  # 三服务：postgres + migrate + backend
└── docs/               # 产品文档、milestone、技能地图
```

## Phase 边界

- **Phase 1**：单用户，4个核心业务全部完成 ✅
- **Phase 2**：多用户 + Expo App + 支付（进行中）
- **Phase 3**：追问能力、跑力画像、多平台适配层、VPS 部署

## 技术注意事项

- 定时用 `AsyncIOScheduler`（async），与 asyncpg + SQLAlchemy async 配套
- Job 失败时走 `notifier.push` 发错误通知，避免静默失败
- `coros_lib/` 内 import 用相对引用（`from .models import ...`）
- 本地开发用 `.env.local` 覆盖 `.env`（DB_URL 指向 localhost:5432），容器内无 `.env.local` 自动降级
- Alembic 迁移通过 `settings.db_url` 读取连接串，`env_file` 已配置 `.env.local` 覆盖
