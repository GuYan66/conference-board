"""解析器 C - 独立站（AAAI / IJCAI）

AAAI 与 IJCAI 官网结构各自独立，非 researchr CMS。
AAAI 页面格式: <strong>July 28, 2026</strong> Full papers due ...
IJCAI 子站 (year.ijcai.org) 结构各异，做尽力提取。

策略: 在全文中找所有长日期 "Month DD, YYYY"，取日期周围的文本判断字段。
"""

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from parsers.researchr import parse_date, AOE, MONTHS, extract_conference_dates

# 独立站专用关键词映射（精确匹配，避免 "submission site opens" 等误匹配）
STANDALONE_KEYWORDS = [
    (["abstracts due", "abstract due", "abstract submission deadline", "abstract deadline"], "abstract"),
    (["full papers due", "full paper due", "papers due", "paper submission deadline", "submission deadline", "paper due"], "submission"),
    (["supplementary material", "supplementary due"], "supplementary"),
    (["author feedback", "rebuttal period"], "rebuttal_start"),
    (["notification of final", "final notification", "final decision", "notification of acceptance"], "notification"),
    (["camera-ready", "camera ready", "submission of camera"], "camera_ready"),
]


def map_field_standalone(text):
    low = re.sub(r"\s+", " ", text.lower()).strip()
    for keywords, field in STANDALONE_KEYWORDS:
        for kw in keywords:
            if kw in low:
                return field
    return None


def parse(html, conf_meta, year):
    result = {
        "deadlines": {},
        "confidence": {},
        "conference_start": None,
        "conference_end": None,
        "place": None,
    }

    soup = BeautifulSoup(html, "lxml")
    page_text = re.sub(r"\s+", " ", soup.get_text(" "))

    # 1. 找所有长日期 "July 28, 2026" / "28 July 2026"，取周围文本判断字段
    #    AAAI 格式: "Date Description" -> 优先看 after
    #    IJCAI 格式: "Description: Date" -> 回退看 before
    for m in re.finditer(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})", page_text):
        date_str = m.group(0)
        dt = _parse_long_date(date_str)
        if not dt:
            continue
        after = page_text[m.end():m.end() + 80]
        before = page_text[max(0, m.start() - 80):m.start()]
        # 优先 after（AAAI "Date Description"），再回退 before（IJCAI "Description: Date"）
        field = map_field_standalone(after) or map_field_standalone(before)
        if field and field not in result["deadlines"]:
            result["deadlines"][field] = dt.isoformat()
            result["confidence"][field] = "medium"

    # 也尝试 researchr 短日期 "May 04 '26"
    for m in re.finditer(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+'(\d{2})", page_text):
        date_str = m.group(0)
        dt = parse_date(date_str)
        if not dt:
            continue
        after = page_text[m.end():m.end() + 80]
        before = page_text[max(0, m.start() - 50):m.start()]
        context = before + " " + after
        field = map_field_standalone(context)
        if field and field not in result["deadlines"]:
            result["deadlines"][field] = dt.isoformat()
            result["confidence"][field] = "medium"

    # 2. 会议日期: 优先选上下文含 "conference" 的 "Month DD-DD, YYYY" 范围
    conf_match = None
    for m in re.finditer(r"([A-Z][a-z]+)\s+(\d{1,2})\s*[-\u2013]\s*(\d{1,2}),?\s+(\d{4})", page_text):
        ctx = page_text[max(0, m.start() - 40):m.end() + 40].lower()
        if "conference" in ctx or "held" in ctx:
            conf_match = m
            break
    if conf_match:
        mon = MONTHS.get(conf_match.group(1)[:3])
        if mon:
            result["conference_start"] = f"{conf_match.group(4)}-{mon:02d}-{int(conf_match.group(2)):02d}"
            result["conference_end"] = f"{conf_match.group(4)}-{mon:02d}-{int(conf_match.group(3)):02d}"
    else:
        # "15-21 of August 2026" 格式
        m = re.search(r"(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\s+of\s+([A-Z][a-z]+),?\s+(\d{4})", page_text)
        if m:
            mon = MONTHS.get(m.group(3)[:3])
            if mon:
                result["conference_start"] = f"{m.group(4)}-{mon:02d}-{int(m.group(1)):02d}"
                result["conference_end"] = f"{m.group(4)}-{mon:02d}-{int(m.group(2)):02d}"
        else:
            start, end = extract_conference_dates(page_text, year)
            if start:
                result["conference_start"] = start
                result["conference_end"] = end

    # 3. 地点: "in Montréal, Canada" / "in Bremen, Germany"（只取 City, Country）
    m = re.search(r"(?:in|from|held in)\s+([A-Z][\w\u00C0-\u017F]+,\s*[A-Z][\w\u00C0-\u017F]+)", page_text)
    if m:
        result["place"] = m.group(1).strip()

    return result


def _parse_long_date(text):
    """解析 "January 22, 2026" / "Jan 22 2026" / "22 January 2026" 等长格式。"""
    months_full = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if m:
        mon = months_full.get(m.group(1).lower())
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(2)), 23, 59, 59, tzinfo=AOE)
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        mon = months_full.get(m.group(2).lower())
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(1)), 23, 59, 59, tzinfo=AOE)
            except ValueError:
                pass
    return None
