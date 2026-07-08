"""
Postgres-backed store，负责去重和原始响应落库。

Tables:
- User: 用户表，身份来自 COROS（coros_user_id 唯一标识）
- ProcessedActivity: 每个用户每条活动 ID 一行（COROS labelId），用于去重
- RunLog: 每个用户每次训练课一行（以第一条活动 ID 为 key），存教练点评
- MorningLog: 每个用户每个睡眠日期一行，存晨报结果
- RiskLog: 每个用户每个检测日期一行，存伤病风险预警
- WeeklyLog: 每个用户每周一行（以周一日期为 key），存周报结果

多用户隔离：除 User 外所有表都用 (user_id, 原业务键) 复合主键，
保证不同用户的同名业务键（比如都在同一天）不会互相覆盖。
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, select
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
    # COROS 自己的用户 ID，来自 COROS 登录响应，App 登录后原样转交给我们，
    # 是唯一权威的身份标识（不是客户端能随意编造的字段）
    coros_user_id = Column(String, unique=True, nullable=False, index=True)
    # 仅用于展示，App 转发过来的邮箱，不作为身份验证依据
    email = Column(String, nullable=True)
    role = Column(String, default="free")  # free / paid
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProcessedActivity(Base):
    __tablename__ = "processed_activities"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    # COROS labelId，同一用户下天然唯一
    label_id = Column(String, primary_key=True)
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MorningLog(Base):
    __tablename__ = "morning_logs"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    sleep_date = Column(String, primary_key=True)  # yyyyMMdd，睡眠所属日期
    raw_sleep = Column(Text)
    raw_hrv = Column(Text)
    raw_daily = Column(Text)
    report = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RiskLog(Base):
    __tablename__ = "risk_logs"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    check_date = Column(String, primary_key=True)  # yyyyMMdd，检测日期，同一天只推一次
    signals = Column(Text)   # 触发的风险信号（JSON 列表）
    report = Column(Text)    # LLM 生成的预警内容
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WeeklyLog(Base):
    __tablename__ = "weekly_logs"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    week_start = Column(String, primary_key=True)  # yyyyMMdd，本周周一日期
    raw_daily = Column(Text)
    raw_sessions = Column(Text)  # 本周活动摘要（含天气）JSON 列表
    report = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RunLog(Base):
    __tablename__ = "run_logs"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    # 复用 labelId 作为行标识，重复写入时可覆盖同一行
    id = Column(String, primary_key=True)  # label_id
    raw_activity = Column(Text)
    raw_daily = Column(Text)
    coaching = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


async def is_processed(user_id: int, label_id: str) -> bool:
    # 每次调用开一个短生命周期 session，查完即关
    async with AsyncSession(get_engine()) as session:
        return await session.get(ProcessedActivity, {"user_id": user_id, "label_id": label_id}) is not None


async def mark_processed(user_id: int, label_id: str):
    # add()：只能插入新记录，主键冲突直接报错（IntegrityError）
    # 语义是"这条记录必须是第一次写入"，比静默覆盖更严格，能暴露重复调用的 bug
    async with AsyncSession(get_engine()) as session:
        session.add(ProcessedActivity(user_id=user_id, label_id=label_id))
        await session.commit()


async def is_morning_report_sent(user_id: int, sleep_date: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(MorningLog, {"user_id": user_id, "sleep_date": sleep_date}) is not None


async def mark_morning_report_sent(user_id: int, sleep_date: str, sleep: dict, hrv: dict, daily: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(MorningLog(
            user_id=user_id,
            sleep_date=sleep_date,
            raw_sleep=json.dumps(sleep, ensure_ascii=False),
            raw_hrv=json.dumps(hrv, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def is_risk_sent(user_id: int, check_date: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(RiskLog, {"user_id": user_id, "check_date": check_date}) is not None


async def mark_risk_sent(user_id: int, check_date: str, signals: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(RiskLog(
            user_id=user_id,
            check_date=check_date,
            signals=json.dumps(signals, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def is_weekly_report_sent(user_id: int, week_start: str) -> bool:
    async with AsyncSession(get_engine()) as session:
        return await session.get(WeeklyLog, {"user_id": user_id, "week_start": week_start}) is not None


async def mark_weekly_report_sent(user_id: int, week_start: str, daily: list, sessions: list, report: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则覆盖，不存在则插入；重跑时安全覆盖旧记录
        await session.merge(WeeklyLog(
            user_id=user_id,
            week_start=week_start,
            raw_daily=json.dumps(daily, ensure_ascii=False),
            raw_sessions=json.dumps(sessions, ensure_ascii=False),
            report=report,
        ))
        await session.commit()


async def save_run_log(user_id: int, label_id: str, activity: dict, daily: dict, coaching: str):
    async with AsyncSession(get_engine()) as session:
        # merge()：主键存在则更新，不存在则插入（upsert）
        # 同一活动因失败重跑时需要覆盖旧记录，所以用 merge 而不是 add
        await session.merge(RunLog(
            user_id=user_id,
            id=label_id,
            raw_activity=json.dumps(activity, ensure_ascii=False),
            raw_daily=json.dumps(daily, ensure_ascii=False),
            coaching=coaching,
        ))
        await session.commit()


async def get_user_by_coros_id(coros_user_id: str) -> User | None:
    async with AsyncSession(get_engine()) as session:
        result = await session.execute(select(User).where(User.coros_user_id == coros_user_id))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> User | None:
    async with AsyncSession(get_engine()) as session:
        return await session.get(User, user_id)


async def get_or_create_user(coros_user_id: str, email: str | None) -> User:
    """
    登录时调用：COROS 校验通过后，按 coros_user_id 找用户，没有就建一个。
    等价于"注册"，但用户感知不到——第一次登录即自动建档。
    """
    user = await get_user_by_coros_id(coros_user_id)
    if user is not None:
        return user

    async with AsyncSession(get_engine()) as session:
        user = User(coros_user_id=coros_user_id, email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
