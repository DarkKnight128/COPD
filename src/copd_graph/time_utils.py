from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now_local() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def local_isoformat(timespec: str = "seconds") -> str:
    return now_local().isoformat(timespec=timespec)
