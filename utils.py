# -*- coding: utf-8 -*-

from datetime import datetime


def sec2str(seconds: int | float):
    seconds = int(seconds)
    parts: list[str] = []
    if day := int(seconds // 86400):
        seconds = seconds % 86400
        parts.append(f"{day} 天")
    if hour := int(seconds // 3600):
        seconds = seconds % 3600
        parts.append(f"{hour} 小时")
    if minute := int(seconds // 60):
        seconds = seconds % 60
        parts.append(f"{minute} 分钟")
    if second := int(seconds):
        parts.append(f"{second} 秒")

    return " ".join(parts)


def ts2str(ts: float):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
