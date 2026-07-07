"""
Postgres-backed store，负责去重和原始响应落库。

Tables:
- ProcessedActivity: 每条活动 ID 一行（COROS labelId），用于去重
- RunLog: 每次训练课一行（以第一条活动 ID 为 key），存教练点评
- MorningLog: 每个睡眠日期一行，存晨报结果
- RiskLog: 每个检测日期一行，存伤病风险预警
- WeeklyLog: 每周一行（以周一日期为 key），存周报结果
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

# engine 延迟初始化：第一次调用 get_engine() 时才创建
# 避免 import store 时立刻读 settings.db_url，让 alembic/env.py 有机会先覆盖环境变量
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.db_url)
    return _engine


class Base(DeclarativeBase):
    # SQLAlchemy 从这个 Base 的 metadata 中读取所有 ORM 模型，用于建表
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="free")  # free / paid
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProcessedActivity(Base):
    __tablename__ = "processed_activities"

    # COROS labelId 是天然的去重主键
    label_id = Column(String, primary_key=True)
    # 记录何时标记为已处理，便于审计
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MorningLog(Base):
    __tablename__ = "morning_logs"

    sleep_date = Column(String, primary_key=True)  # yyyyMMdd，睡眠所属日期
    raw_sleep = Column(Text)
    raw_hrv = Column(Text)
    raw_daily = Column(Text)
    report = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RiskLog(Base):
    __tablename__ = "risk_logs"

    check_date = Column(String, primary_key=True)  # yyyyMMdd，检测日期，同一天只推一次
    signals = Column(Text)   # 触发的风险信号（JSON 列表）
    report = Column(Text)    # LLM 生成的预警内容
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WeeklyLog(Base):
    __tablename__ = "weekly_logs"

    week_start = Column(String, primary_key=True)  # yyyyMMdd，本周周一日期
    raw_daily = Column(Text)
    raw_sessions = Column(Text)  # 本周活动摘要（含天气）JSON 列表
    report = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RunLog(Base):
    __tablename__ = "run_logs"

    # 复用 labelId 作为行标识，重复写入时可覆盖同一行
    id = Column(String, primary_key=True)  # label_id
    # 原始数据存 JSON 文本，便于调试和回放
    raw_activity = Column(Text)
    raw_daily = Column(Text)
    coaching = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


async def is_processed(label_id: str) -> bool:
    # 每次调用开一个短生命周期 session，查完即关
    async with AsyncSession(get_engine()) as session:
        return await session.get(ProcessedActivity, label_id) is not None


async def mark_processed(label_id: str):
    # add()：只能插入新记录，主键冲突直接报错（IntegrityError）
    # 语义是"这条记录必须是第一次写入"，比静默覆盖更严格，能暴露重复调用的 bug
    async with AsyncSession(get_engine()) as session:
        session.add(ProcessedActivity(label_id=label_id))
        await session.commit()


async def is_morning_report_sent(sleep_date: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(MorningLog, sleep_date) is not None


async def mark_morning_report_sent(sleep_date: str, sleep: dict, hrv: dict, daily: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(MorningLog(
            sleep_date=sleep_date,
            raw_sleep=json.dumps(sleep, ensure_ascii=False),
            raw_hrv=json.dumps(hrv, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def is_risk_sent(check_date: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(RiskLog, check_date) is not None


async def mark_risk_sent(check_date: str, signals: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(RiskLog(
            check_date=check_date,
            signals=json.dumps(signals, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def is_weekly_report_sent(week_start: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(WeeklyLog, week_start) is not None


async def mark_weekly_report_sent(week_start: str, daily: list, sessions: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(WeeklyLog(
            week_start=week_start,
            raw_daily=json.dumps(daily, ensure_ascii=False),
            raw_sessions=json.dumps(sessions, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def save_run_log(label_id: str, activity: dict, daily: dict, coaching: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则更新，不存在则插入（upsert）
        # 同一活动因失败重跑时需要覆盖旧记录，所以用 merge 而不是 add
        await session.merge(RunLog(
            id=label_id,
            raw_activity=json.dumps(activity, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            coaching=coaching,
        ))
        await session.commit()


async def get_user_by_email(email: str) -> User | None:
    async with AsyncSession(get_engine()) as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> User | None:
    async with AsyncSession(get_engine()) as session:
        return await session.get(User, user_id)


async def create_user(email: str, password_hash: str) -> User:
    async with AsyncSession(get_engine()) as session:
        user = User(email=email, password_hash=password_hash)
        session.add(user)
        await session.commit()
        await session.refresh(user)  # 拿到数据库生成的 id、created_at
        return user
