# pace-core · CLAUDE.md

## 项目简介

PaceCoach Phase 1 后端。轮询 COROS 手表数据，练后自动触发 LLM 生成教练点评，通过 Ntfy 推送到手机。

## 协作约定

**学习优先**：这是 Kevin 的第二个全栈项目，目标是实践学习，不是快速产品化。

- 解释架构决策背后的"为什么"，不只是"怎么做"
- 终端命令列出来让用户自己跑，不要自动执行安装/初始化命令
- 遇到多种方案时，说清楚 tradeoff，让用户自己选
- **动手前先说方案**：描述打算怎么做，Kevin 确认方向后再实现，不一次性堆满细节
- Kevin 来做判断和决策，Claude 负责实现；语法细节不深究，业务和工程判断必须 figure out

## 项目结构

```
pace-core/
├── coros_lib/          # vendor 自 cygnusb/coros-mcp（MIT），只保留取数函数
├── src/
│   ├── config.py       # 读 .env，所有配置集中在这里
│   ├── coros_client.py # 薄封装 coros_lib，工具型函数（Phase 2 直接变 agent tools）
│   ├── analyzer.py     # LLM 分析，analyze_workout()（启用）/ analyze_sleep()（挂起）
│   ├── notifier.py     # push()，v0 走 Ntfy，Phase 2 换 Expo Push 只改这一个文件
│   ├── store.py        # SQLite 去重 + RunLog
│   └── jobs.py         # on_new_activity()（启用）/ morning_report()（挂起）
├── main.py             # 入口，BlockingScheduler 装配；--once 手动触发
└── test_connection.py  # 第一个验证门：能否拉到 COROS 数据
```

## Phase 边界

- **Phase 1 v0**：练后分析推送（本仓当前目标）
- **Phase 1 v0.1**：晨起睡眠简报（代码路径已搭，job 挂起，有数据后激活）
- **Phase 2**：agent 交互、Expo App 前端（另起仓库）

## 技术注意事项

- 定时用 `BlockingScheduler`（同步），不用 `AsyncIOScheduler`，避免与同步 SQLAlchemy 混用的复杂度
- Job 失败时走 `notifier.push` 发错误通知，避免静默失败
- `coros_lib/` 内 import 用相对引用（`from .models import ...`）
- DB_URL 现在是 SQLite，Phase 2 换 Postgres 只改连接串
