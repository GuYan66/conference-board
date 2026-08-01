"""解析器 A - researchr CMS 系（NeurIPS / ICML / ICLR / CVPR）

这些会议官网共用同一套 CMS，Dates 页面结构高度一致：
- 时间节点用 <table> 组织，每个节点是一个 <tr>
- 节点名在 <td title="..."> 或 <td><a>文本</a></td>（title 可能为空）
- 日期在相邻的下一个 <td>，格式形如 "May 04 '26 (Anywhere on Earth)"
"""

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

# AoE (Anywhere on Earth) = UTC-12
AOE = timezone(timedelta(hours=-12))

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# 节点名关键词 -> schema 字段（按优先级排序，首个匹配生效）
# 注意: notification 收窄，避免误匹配 "Volunteer Application Notification" 等
KEYWORD_MAP = [
    (["abstract submission", "abstract deadline"], "abstract"),
    (["full paper submission", "paper submission deadline", "paper registration"], "submission"),
    (["supplementary material"], "supplementary"),
    (["review released", "reviews released", "rebuttal period starts"], "rebuttal_start"),
    (["rebuttal period ends", "discussion period ends"], "rebuttal_end"),
    (["paper author notification", "paper decision notification", "final decision"], "notification"),
    (["camera ready"], "camera_ready"),
]


def parse_date(text):
    """从文本中解析日期，返回 AoE 时区的 datetime。

    支持格式:
      "May 04 '26 (Anywhere on Earth)"
      "May 04 '26"
      "May 4 '26"
    """
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+'(\d{2})", text)
    if not m:
        return None
    mon = MONTHS.get(m.group(1))
    if not mon:
        return None
    day = int(m.group(2))
    year = 2000 + int(m.group(3))
    try:
        return datetime(year, mon, day, 23, 59, 59, tzinfo=AOE)
    except ValueError:
        return None


def extract_conference_dates(page_text, year):
    """从页面文本提取会议日期范围，返回 (start_str, end_str)。

    处理带序数后缀的格式，取跨度最大的范围作为整体会议日期:
      "Dec 6th through Sat Dec 12th"
      "June 5 - 7"
      "April 23 through Saturday April 25"
    """
    best = None  # (span, mon, d_start, d_end)
    # "Dec 6th through Sat Dec 12th"（含序数后缀，跨月可能）
    for m in re.finditer(
        r"([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\s+through\s+"
        r"(?:[A-Z][a-z]+\s+)?([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?",
        page_text,
    ):
        mon1 = MONTHS.get(m.group(1))
        mon2 = MONTHS.get(m.group(3))
        if not (mon1 and mon2):
            continue
        d1, d2 = int(m.group(2)), int(m.group(4))
        span = abs(d2 - d1) + (0 if mon1 == mon2 else 31)
        if best is None or span > best[0]:
            best = (span, mon1, d1, mon2, d2)
    if best:
        _, mon1, d1, mon2, d2 = best
        start = f"{year}-{mon1:02d}-{d1:02d}"
        end = f"{year}-{mon2:02d}-{d2:02d}"
        return start, end
    # 回退: "June 5 - 7" 同月简写，取跨度最大（优先 Main Conference 而非 Workshops）
    best2 = None
    for m in re.finditer(r"([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})\s*[-\u2013]\s*(\d{1,2})", page_text):
        mon = MONTHS.get(m.group(1))
        if mon:
            span = abs(int(m.group(3)) - int(m.group(2)))
            if best2 is None or span > best2[0]:
                best2 = (span, mon, int(m.group(2)), int(m.group(3)))
    if best2:
        return (
            f"{year}-{best2[1]:02d}-{best2[2]:02d}",
            f"{year}-{best2[1]:02d}-{best2[3]:02d}",
        )
    return None, None


def map_field(name):
    """将节点名映射到 schema 字段，未匹配返回 None。"""
    low = re.sub(r"\s+", " ", name.lower()).strip()
    for keywords, field in KEYWORD_MAP:
        for kw in keywords:
            if kw in low:
                return field
    return None


def parse(html, conf_meta, year):
    """解析 researchr CMS 的 Dates 页面。

    Args:
        html: 页面 HTML 文本
        conf_meta: config.yml 中该会议的元数据 (id/title/category 等)
        year: 会议年份

    Returns:
        dict: 含 deadlines/confidence/conference_start/end/place 等字段
    """
    soup = BeautifulSoup(html, "lxml")
    result = {
        "deadlines": {},
        "confidence": {},
        "conference_start": None,
        "conference_end": None,
        "place": None,
    }

    # 1. 提取时间节点: 遍历所有 <tr> 的 <td>，取 title 或文本作为节点名
    #    （ICLR/CVPR 的 td title 为空，节点名在 <a> 文本内）
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        for idx, td in enumerate(tds):
            title = (td.get("title") or "").strip()
            name = title or td.get_text(strip=True)
            if not name:
                continue
            field = map_field(name)
            if not field or field in result["deadlines"]:
                continue
            # 日期在下一个 td
            if idx + 1 >= len(tds):
                continue
            date_text = tds[idx + 1].get_text(strip=True)
            if not date_text or date_text in ("-", "TBD", "TBA"):
                continue
            dt = parse_date(date_text)
            if dt:
                result["deadlines"][field] = dt.isoformat()
                result["confidence"][field] = "high"

    # 2. 提取会议日期: 取跨度最大的日期范围
    page_text = soup.get_text(" ")
    start, end = extract_conference_dates(page_text, year)
    if start:
        result["conference_start"] = start
        result["conference_end"] = end

    # 3. 提取地点: 尽力提取，失败为 None
    place = _extract_place(page_text)
    if place:
        result["place"] = place

    return result


def _extract_place(page_text):
    """尽力从页面提取地点。researchr 页面地点信息通常较少，返回 None 则标记 missing。"""
    m = re.search(r"held in ([A-Z][A-Za-z .,']+(?:[A-Z][A-Za-z]+)*)", page_text)
    if m:
        return m.group(1).strip().rstrip(",")
    m = re.search(r"Location[:\s]+([A-Z][A-Za-z ,.]+)", page_text)
    if m:
        return m.group(1).strip().rstrip(".")[:60]
    return None
