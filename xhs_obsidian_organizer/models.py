from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_LEVEL_NAMES = {"A": "高意向", "B": "中意向", "C": "低意向", "D": "暂不跟进"}


class UserRecord:
    """一条用户评论记录"""

    def __init__(
        self,
        nickname: str,
        comment: str,
        likes: int,
        timestamp: int,
        source_note: str,
        source_keyword: str,
        source_date: str,
        tags: list[str],
    ):
        self.nickname = nickname
        self.comment = comment
        self.likes = likes
        self.timestamp = timestamp
        self.source_note = source_note
        self.source_keyword = source_keyword
        self.source_date = source_date
        self.tags = tags
        self.replies: list[dict] = []

        self.comment_length = len(comment)
        self.has_question = any(kw in comment for kw in ("?", "？", "怎么", "如何", "求", "有没"))
        self.has_request = any(kw in comment for kw in ("求资料", "求教程", "求分享", "求推荐"))
        self.is_meaningful = self.comment_length > 30 and not self.has_request

    @property
    def level(self) -> str:
        if self.likes >= 5 or self.is_meaningful:
            return "A"
        if self.comment_length > 20 or (self.has_question and not self.has_request):
            return "B"
        if self.has_request or self.comment_length > 5:
            return "C"
        return "D"

    @property
    def date_str(self) -> str:
        ts = self.timestamp / 1000 if self.timestamp > 1e11 else self.timestamp
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    @property
    def location(self) -> str:
        return "未知"

    def to_dict(self) -> dict:
        return {
            "昵称": self.nickname,
            "评论": self.comment[:80],
            "评论长度": self.comment_length,
            "点赞": self.likes,
            "等级": self.level,
            "日期": self.date_str,
            "地域": self.location,
            "来源笔记": self.source_note,
            "来源关键词": self.source_keyword,
            "互动": len(self.replies),
        }


class Contact:
    """按昵称聚合后的联系人"""

    def __init__(self, nickname: str):
        self.nickname = nickname
        self.records: list[UserRecord] = []

    def add_record(self, r: UserRecord):
        self.records.append(r)

    @property
    def keywords(self) -> list[str]:
        return list(dict.fromkeys(r.source_keyword for r in self.records if r.source_keyword))

    @property
    def total_comments(self) -> int:
        return len(self.records)

    @property
    def total_likes(self) -> int:
        return sum(r.likes for r in self.records)

    @property
    def avg_length(self) -> float:
        return sum(r.comment_length for r in self.records) / max(len(self.records), 1)

    @property
    def first_date(self) -> str:
        return min(r.date_str for r in self.records)

    @property
    def last_date(self) -> str:
        return max(r.date_str for r in self.records)

    @property
    def signal_keywords(self) -> list[str]:
        signals: list[str] = []
        for r in self.records:
            if r.has_request:
                signals.append("有索取行为")
            if r.is_meaningful:
                signals.append("有质量评论")
            if r.likes >= 3:
                signals.append("高赞")
        return list(dict.fromkeys(signals))

    @property
    def score(self) -> int:
        if not self.records:
            return 0

        avg_len = self.avg_length
        unique_keywords = len(self.keywords)
        total_likes = self.total_likes
        has_reply = any(len(r.replies) > 0 for r in self.records)
        days_since = (datetime.now() - datetime.strptime(self.last_date, "%Y-%m-%d")).days

        len_score = min(100, avg_len * 2)
        like_score = min(100, total_likes * 8)
        keyword_score = min(100, unique_keywords * 25)

        signal_score = 0
        if any(r.is_meaningful for r in self.records):
            signal_score += 40
        if any(r.has_request for r in self.records):
            signal_score += 25
        if total_likes >= 5:
            signal_score += 20
        if has_reply:
            signal_score += 15

        reply_score = 30 if has_reply else 10
        recency_score = max(0, 100 - days_since)

        score = (
            len_score * 0.15
            + like_score * 0.15
            + keyword_score * 0.25
            + signal_score * 0.20
            + reply_score * 0.15
            + recency_score * 0.10
        )
        return round(min(100, max(0, score)))

    @property
    def level(self) -> str:
        s = self.score
        if s >= 65:
            return "A"
        if s >= 45:
            return "B"
        if s >= 20:
            return "C"
        return "D"

    @property
    def best_comment(self) -> str:
        best = max(self.records, key=lambda r: (r.likes, r.comment_length))
        return best.comment[:120]

    def comment_summary(self) -> list[dict]:
        return [
            {"keyword": r.source_keyword, "note": r.source_note,
             "comment": r.comment[:80], "likes": r.likes, "date": r.date_str,
             "replies": len(r.replies)}
            for r in sorted(self.records, key=lambda x: x.timestamp, reverse=True)
        ]
