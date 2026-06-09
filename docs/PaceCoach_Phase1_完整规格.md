# PaceCoach · pace-core · Phase 1 完整规格（档位 1 · 自用 · 最终版）

> **App 名**：PaceCoach｜**仓库名**：pace-core  
> 档位 1 = 为自己一个人跑通整条管道，验证产品假设，不做多用户、不做 UI。  
> v0 先跑通**练后分析推送**（已用真实数据验证有价值）；晨起睡眠简报代码路径搭好但挂起（暂无睡眠数据，待戴表睡一晚后再测）。  
> agent 是 Phase 2 的事，本文档只为它留好地基（取数函数做成工具型）。

---

## 一、功能边界

### v0（必做）— 目标：近期跑通

| 功能                 | 说明                                                                          |
| -------------------- | ----------------------------------------------------------------------------- |
| **练后即时分析推送** | 检测到新活动 → 拉详情 + 近 14 天训练指标 → LLM 生成教练点评 → Ntfy 推送到手机 |

### v0.1（必做，有数据后补）

| 功能                  | 说明                                                  |
| --------------------- | ----------------------------------------------------- |
| **晨起睡眠/恢复推送** | 每天固定时间 → 拉昨晚睡眠 + HRV → LLM 生成简报 → 推送 |

> ⏸ 暂无睡眠数据（未戴表入睡），代码路径搭好但 job 挂起，有数据立即激活。

### 明确不做（Phase 1 边界）

交互式问答 / agent（Phase 2）、多用户（档位 2）、前端 App（档位 2）、多平台数据源、WebSocket

---

## 二、技术栈（全部锁定）

| 层              | 选型                                          | 说明                                                                            |
| --------------- | --------------------------------------------- | ------------------------------------------------------------------------------- |
| 语言            | Python 3.11+                                  |                                                                                 |
| 数据层          | `coros_lib/`（vendor cygnusb/coros-mcp, MIT） | 裁剪后只保留取数函数                                                            |
| 定时            | APScheduler（BlockingScheduler）              | 同步轮询；进程内，档位 2 换 Celery                                              |
| ORM + 存储      | SQLAlchemy 2.0 + SQLite                       | 档位 2 换 Postgres，只改连接串                                                  |
| LLM             | OpenAI-compatible SDK（Qwen）                 | analyzer.py 内部封装，通过 base_url / model 切换具体供应商                      |
| 推送（v0）      | **Ntfy**（ntfy.sh，免费）                     | Android + iOS 通用，后端一行 POST                                               |
| 推送（Phase 2） | Expo Push（FCM/APNs）                         | Expo App 上线后替换 notifier.py，其他零改动                                     |
| Web 框架        | FastAPI                                       | 加进 requirements 占位，**v0 不跑 HTTP server**；Expo App 需调后端时再写 routes |
| 运行            | 本机 Mac（M4 Pro）                            | 档位 2 上 Hetzner/DO VPS + Docker                                               |
| 区域            | `region="cn"`                                 | → teamcnapi.coros.com（Web）/ apicn.coros.com（移动端/睡眠）                    |

---

## 三、Ntfy 推送接入（5 分钟，免费）

1. 手机安装 **Ntfy App**（Android / iOS）。
2. 订阅 topic，如 `pacecoach-kevin`。
3. 后端推送（5 行代码）：

```python
import httpx
httpx.post(f"https://ntfy.sh/{settings.NTFY_TOPIC}",
           content=body.encode(),
           headers={"Title": title})
```

4. 等 Expo App 上线后，将 notifier.py 内部实现换成 Expo Push API，其余代码零改动。

---

## 四、cygnusb 数据层裁剪

来源：`github.com/cygnusb/coros-mcp`（MIT），vendor 三文件到 `coros_lib/`。

**Phase 1 v0 保留**

| 函数                       | 用途                                                        |
| -------------------------- | ----------------------------------------------------------- |
| `login` / `try_auto_login` | 认证，token 自动刷新                                        |
| `fetch_activities`         | 拉最近 N 条活动，找新的                                     |
| `fetch_activity_detail`    | 单次活动详情（配速/心率/步频/负荷）                         |
| `fetch_daily_records`      | VO2max + 训练负荷 + 负荷比（合并 analyse + analyse_detail） |

**Phase 1 v0.1 保留（睡眠场景）**

| 函数          | 用途       |
| ------------- | ---------- |
| `fetch_sleep` | 睡眠分段   |
| `fetch_hrv`   | 夜间 RMSSD |

**删除**：`fetch_workout_templates`、`save/delete_workout_template`、`fetch_schedule`、`schedule_*`、`save_strength_workout_template`、`fetch_exercises`、`_load_strength_catalog` 及相关私有辅助函数。

**import 修正**：移入 `coros_lib/` 后，`coros_api.py` 内的 import 改为相对引用（`from .models import ...`、`from .auth_storage import ...`）。

---

## 五、场景 1 数据流

```
[BlockingScheduler 每 N 分钟轮询]
  → coros_client.get_recent_activities()
  → 过滤 store 中已处理的 labelId（去重）
  → 对每条新活动：
       activity  = coros_client.get_activity_detail(labelId, sportType)
       daily_ctx = coros_client.get_recent_daily_records(days=14)
  → coaching = analyzer.analyze_workout(activity, daily_ctx)
  → notifier.push(title="练后点评", body=coaching)
  → store.mark_processed(labelId)
```

**analyzer prompt 核心原则**（已用真实数据验证）：把本次活动配速/心率放在近期负荷趋势里解读，指出今天与近期同类跑的异同，给一条可执行建议；字数 200 字以内（推送场景）；不要复述单个指标，要连线叙事。

---

## 六、项目结构

```
pace-core/
├── .env.example
├── requirements.txt
├── README.md
│
├── coros_lib/                # vendor 自 cygnusb（MIT），裁剪 + 修 import
│   ├── __init__.py
│   ├── coros_api.py          # 保留：login / fetch_activities / fetch_activity_detail
│   │                         #        / fetch_daily_records / fetch_sleep / fetch_hrv
│   ├── models.py             # pydantic 模型
│   └── auth_storage.py       # token 存取
│
├── src/
│   ├── __init__.py
│   ├── config.py             # 读 .env，集中所有配置
│   ├── coros_client.py       # 薄封装：工具型函数（Phase 2 直接变 agent tools）
│   │                         #   get_recent_activities() / get_activity_detail()
│   │                         #   get_recent_daily_records() / get_sleep() / get_hrv()
│   ├── analyzer.py           # analyze_workout()（启用）/ analyze_sleep()（挂起）
│   ├── notifier.py           # push()：v0 走 Ntfy
│   ├── store.py              # SQLAlchemy + SQLite：ProcessedActivity 去重 + RunLog
│   └── jobs.py               # on_new_activity()（启用）/ morning_report()（挂起）
│
├── test_connection.py        # 验证数据能拉出来（第一个验证门）
└── main.py                   # BlockingScheduler 装配；--once 手动触发测试
```

**.env.example**

```
COROS_EMAIL=
COROS_PASSWORD=
COROS_REGION=
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
NTFY_TOPIC=
DB_URL=
POLL_INTERVAL_MINUTES=
```

**requirements.txt**

```
httpx
pydantic>=2.0
cryptography
pycryptodome>=3.0
python-dotenv>=1.0
sqlalchemy>=2.0
apscheduler>=3.10
openai
fastapi
uvicorn
```

---

## 七、容错（从第一天做进去）

`coros_client.py` 内部处理：重试（指数退避，最多 3 次）、token 失效自动重登（try_auto_login）、任一取数失败返回明确错误对象（不崩整个 job）、原始响应写 RunLog（接口变更时可回放调试）。

---

## 八、验证标准（Phase 1 v0 怎么算跑通）

| 验证点       | 方式                                                           |
| ------------ | -------------------------------------------------------------- |
| 数据能拉出来 | `python test_connection.py` 打印最近活动列表                   |
| 分析有价值   | 推送内容连线"本次活动 + VO2max + 近期负荷趋势"，给出可执行建议 |
| 推送到手机   | Android Ntfy App 收到通知，标题 + 正文清晰可读                 |
| 去重正常     | 同一活动 `--once` 跑两次，第二次不重复推送                     |
| 自动触发     | 真实跑步结束数据同步后，scheduler 自动触发并推送               |

全部通过 = Phase 1 v0 完成。立即进 Phase 2 或按错峰节奏切回图片 spike，不加任何额外功能。

---
