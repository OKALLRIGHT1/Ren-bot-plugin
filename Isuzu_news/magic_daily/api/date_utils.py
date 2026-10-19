"""
日期工具模块
用于获取当前日期、星期、农历等信息
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, Optional

# 星期映射
WEEKDAYS_CN = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}

ALAPI_LUNAR_URL = "https://v3.alapi.cn/api/lunar"
_ALAPI_TOKEN = ""
_ALAPI_TIMEOUT_SEC = 5


def set_alapi_token(token: str):
    global _ALAPI_TOKEN
    _ALAPI_TOKEN = str(token or "").strip()


def get_current_date_info() -> Dict[str, str]:
    """
    获取当前日期信息

    Returns:
        {
            "week_cn": "星期一",
            "date_str": "2024-01-15",
            "cn_date_str": "腊月初五"
        }
    """
    now = datetime.now()

    # 星期
    week_cn = WEEKDAYS_CN[now.weekday()]

    # 日期字符串
    date_str = now.strftime("%Y-%m-%d")

    # 农历日期
    cn_date_str = get_lunar_date(now)

    return {
        "week_cn": week_cn,
        "date_str": date_str,
        "cn_date_str": cn_date_str,
    }


def _request_alapi_lunar(date_obj: datetime, token: Optional[str]) -> Optional[dict]:
    payload = {"date": date_obj.strftime("%Y-%m-%d %H:%M"), "unix_time": ""}
    if token:
        payload["token"] = token

    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["token"] = token

    # Try POST first
    try:
        req = urllib.request.Request(ALAPI_LUNAR_URL, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_ALAPI_TIMEOUT_SEC) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8", "ignore") or "{}")
    except Exception:
        pass

    # Fallback to GET
    try:
        query = urllib.parse.urlencode(payload)
        with urllib.request.urlopen(f"{ALAPI_LUNAR_URL}?{query}", timeout=_ALAPI_TIMEOUT_SEC) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8", "ignore") or "{}")
    except Exception:
        return None


def _format_lunar_from_numbers(month_num: int, day_num: int, is_leap: bool = False) -> str:
    if not month_num or not day_num:
        return ""
    lunar_months = ["", "正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "腊"]
    month_name = lunar_months[month_num] if 0 < month_num < len(lunar_months) else str(month_num)
    if is_leap:
        month_name = f"闰{month_name}"

    if day_num == 1:
        day_name = "初一"
    elif day_num <= 10:
        day_names = ["", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十"]
        day_name = day_names[day_num]
    elif day_num < 20:
        tens = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        day_name = f"十{tens[day_num - 10]}"
    elif day_num == 20:
        day_name = "二十"
    elif day_num < 30:
        tens = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        day_name = f"廿{tens[day_num - 20]}"
    else:
        day_name = "三十"

    return f"{month_name}月{day_name}"


def _extract_lunar_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    if not isinstance(data, dict):
        return ""

    # ALAPI standard fields (preferred)
    month_cn = data.get("lunar_month_chinese") or data.get("lunar_month_cn") or data.get("month_cn") or data.get("IMonthCn")
    day_cn = data.get("lunar_day_chinese") or data.get("lunar_day_cn") or data.get("day_cn") or data.get("IDayCn")
    if month_cn and day_cn:
        month_cn = str(month_cn).strip()
        day_cn = str(day_cn).strip()
        if data.get("is_leap") or data.get("leap"):
            if not month_cn.startswith("闰"):
                month_cn = f"闰{month_cn}"
        return f"{month_cn}{day_cn}"

    for key in ("lunarDate", "lunar_date", "lunar", "lunar_cn", "lunar_date_cn"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    lunar = data.get("lunar")
    if isinstance(lunar, dict):
        month_cn = lunar.get("lunar_month_chinese") or lunar.get("lunar_month_cn") or lunar.get("IMonthCn")
        day_cn = lunar.get("lunar_day_chinese") or lunar.get("lunar_day_cn") or lunar.get("IDayCn")
        if month_cn and day_cn:
            month_cn = str(month_cn).strip()
            day_cn = str(day_cn).strip()
            if lunar.get("is_leap") or lunar.get("leap"):
                if not month_cn.startswith("闰"):
                    month_cn = f"闰{month_cn}"
            return f"{month_cn}{day_cn}"
        for key in ("lunarDate", "lunar_date", "lunar_cn"):
            value = lunar.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        month_num = lunar.get("lunar_month") or lunar.get("month")
        day_num = lunar.get("lunar_day") or lunar.get("day")
        if isinstance(month_num, int) and isinstance(day_num, int):
            return _format_lunar_from_numbers(month_num, day_num, bool(lunar.get("leap") or lunar.get("is_leap")))

    month_num = data.get("lunar_month") or data.get("month")
    day_num = data.get("lunar_day") or data.get("day")
    if isinstance(month_num, int) and isinstance(day_num, int):
        return _format_lunar_from_numbers(month_num, day_num, bool(data.get("is_leap") or data.get("leap")))

    return ""


def get_lunar_date(date_obj: datetime) -> str:
    """
    获取农历日期
    优先使用 ALAPI lunar 接口，失败后回退到 zhdate

    Args:
        date_obj: 日期对象

    Returns:
        农历日期字符串，例如"腊月初五"；失败时返回"农历未知"
    """
    try:
        payload = _request_alapi_lunar(date_obj, _ALAPI_TOKEN)
        if payload:
            lunar_text = _extract_lunar_text(payload)
            if lunar_text:
                return lunar_text
    except Exception:
        pass

    try:
        from zhdate import ZhDate

        lunar = ZhDate.from_datetime(date_obj)
        return _format_lunar_from_numbers(
            lunar.lunar_month,
            lunar.lunar_day,
            bool(getattr(lunar, "leap", False)),
        )
    except ImportError:
        return "农历未知"
    except Exception:
        return "农历未知"
