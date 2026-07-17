from datetime import datetime

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query

from api.deps import get_current_user
from src import store
from src.store import User

router = APIRouter()


class FeedItem(BaseModel):
    id: str
    type: str  # "run" | "morning" | "risk" | "weekly"
    timestamp: datetime
    summary: str


@router.get("", response_model=list[FeedItem])
async def get_feed(
    before: datetime | None = None,
    limit: int = Query(default=20, le=50),
    current_user: User = Depends(get_current_user),
):
    """
    历史记录时间线，纯读取，不触发任何新分析。
    分页用时间游标：不传 before 拿最新一页，翻页时传上一页最后一条的 timestamp。
    """
    items = await store.get_feed_items(current_user.id, before=before, limit=limit)
    return items
