"""ccf-deadlines 数据补充模块

从 ccf-deadlines GitHub 仓库获取会议数据，补充官网缺失的地点、会议日期等信息。
数据源: https://github.com/ccfddl/ccf-deadlines
"""

import re

import requests
import yaml
from datetime import datetime, timedelta, timezone

AOE = timezone(timedelta(hours=-12))

# config.yml id -> ccf-deadlines 相对路径 (子目录/文件名, 不含 .yml)
# ccf-deadlines 仓库按 CCF 类别分子目录存放: AI/ DB/ IR/ MX/ CG/ 等。
# 注意 CVPR/ICCV/ECCV 等视觉会议在 ccf 中归在 AI/ 下，而非 CV/。
FILE_MAP = {
    # 现有 8 会
    "neurips": "AI/nips",
    "icml": "AI/icml",
    "iclr": "AI/iclr",
    "aaai": "AI/aaai",
    "ijcai": "AI/ijcai",
    "cvpr": "AI/cvpr",
    "iccv": "AI/iccv",
    "eccv": "AI/eccv",
    # 新增
    "wsdm": "DB/wsdm",
    "icra": "AI/icra",
    "naacl": "AI/naacl",
    "www": "MX/www",
}

# ccf-deadlines 镜像列表(按优先级)。raw.githubusercontent 在部分网络(如企业网/国内)
# 下被阻断，故优先用 jsDelivr CDN 镜像。{} 处填 FILE_MAP 的相对路径(如 AI/iclr)。
MIRRORS = [
    "https://fastly.jsdelivr.net/gh/ccfddl/ccf-deadlines@main/conference/{}.yml",
    "https://cdn.jsdelivr.net/gh/ccfddl/ccf-deadlines@main/conference/{}.yml",
    "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/{}.yml",
]

# 同 scraper.py: 直连，绕过失效的本地系统代理。
NO_PROXY = {"http": None, "https": None}

MONTHS_FULL = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_cache = {}
_working_idx = None  # 缓存首个可用镜像在 MIRRORS 中的下标，避免每次会议都逐个试探


def fetch_ccf_data(conf_id):
    """获取 ccf-deadlines 中该会议的所有届次数据（带缓存）。"""
    if conf_id in _cache:
        return _cache[conf_id]
    relpath = FILE_MAP.get(conf_id)
    if not relpath:
        _cache[conf_id] = []
        return []
    # 已知可用镜像则直接用；否则按优先级逐个试探，命中后记住下标
    global _working_idx
    if _working_idx is not None:
        candidates = [(_working_idx, MIRRORS[_working_idx].format(relpath))]
    else:
        candidates = list(enumerate(m.format(relpath) for m in MIRRORS))
    for idx, url in candidates:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, proxies=NO_PROXY)
            if r.status_code == 200:
                if _working_idx is None:
                    _working_idx = idx
                data = yaml.safe_load(r.text)
                confs = data[0]["confs"] if isinstance(data, list) else data.get("confs", [])
                _cache[conf_id] = confs
                return confs
        except Exception:
            continue
    _cache[conf_id] = []
    return []


def parse_ccf_date(date_str, year):
    """解析 ccf date 字段，如 'July 6-12, 2026' / 'June 3-7, 2026' -> (start, end)。"""
    if not date_str:
        return None, None
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})\s*[-\u2013]\s*(\d{1,2}),?\s+(\d{4})", str(date_str))
    if m:
        mon = MONTHS_FULL.get(m.group(1).lower())
        if mon:
            return (
                f"{m.group(4)}-{mon:02d}-{int(m.group(2)):02d}",
                f"{m.group(4)}-{mon:02d}-{int(m.group(3)):02d}",
            )
    # 跨月: "Jan 30-Feb 3, 2027"
    m = re.search(
        r"([A-Z][a-z]+)\s+(\d{1,2})\s*[-\u2013]\s*([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        str(date_str),
    )
    if m:
        mon1 = MONTHS_FULL.get(m.group(1).lower())
        mon2 = MONTHS_FULL.get(m.group(3).lower())
        if mon1 and mon2:
            y = m.group(5)
            return (
                f"{y}-{mon1:02d}-{int(m.group(2)):02d}",
                f"{y}-{mon2:02d}-{int(m.group(4)):02d}",
            )
    return None, None


def parse_ccf_deadline(deadline_str):
    """解析 ccf deadline '2026-01-29 11:59:59' -> ISO 8601 AoE。"""
    try:
        dt = datetime.strptime(str(deadline_str), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=AOE).isoformat()
    except (ValueError, TypeError):
        return None


def supplement_entry(entry, conf_id):
    """用 ccf-deadlines 数据补充 entry 的缺失字段（place、会议日期、deadline）。"""
    confs = fetch_ccf_data(conf_id)
    if not confs:
        return entry

    target_year = entry.get("year")
    matched = None
    for c in confs:
        if int(c.get("year", 0)) == target_year:
            matched = c
            break
    if not matched:
        return entry

    confidence = entry.setdefault("confidence", {})
    deadlines = entry.setdefault("deadlines", {})

    # 补充 place
    if not entry.get("place") and matched.get("place"):
        entry["place"] = matched["place"]
        confidence["place"] = "medium"

    # 补充会议日期
    if not entry.get("conference_start") and matched.get("date"):
        start, end = parse_ccf_date(matched["date"], target_year)
        if start:
            entry["conference_start"] = start
            entry["conference_end"] = end

    # 补充 deadline（官网没抓到的字段）
    timeline = {}
    if matched.get("timeline"):
        timeline = matched["timeline"][0] if isinstance(matched["timeline"], list) else matched["timeline"]

    if not deadlines.get("submission") and timeline.get("deadline"):
        iso = parse_ccf_deadline(timeline["deadline"])
        if iso:
            deadlines["submission"] = iso
            confidence["submission"] = "medium"
    if not deadlines.get("abstract") and timeline.get("abstract_deadline"):
        iso = parse_ccf_deadline(timeline["abstract_deadline"])
        if iso:
            deadlines["abstract"] = iso
            confidence["abstract"] = "medium"

    return entry


def find_future_entry(conf_id, after_year, now):
    """从 ccf-deadlines 找比 after_year 更未来且投稿未截止的届次。

    返回 ccf 届次 dict 或 None。
    """
    confs = fetch_ccf_data(conf_id)
    for c in sorted(confs, key=lambda x: int(x.get("year", 0)), reverse=True):
        if int(c.get("year", 0)) <= after_year:
            continue
        timeline = {}
        if c.get("timeline"):
            timeline = c["timeline"][0] if isinstance(c["timeline"], list) else c["timeline"]
        dl = timeline.get("deadline")
        if not dl:
            continue
        iso = parse_ccf_deadline(dl)
        if iso:
            dt = datetime.fromisoformat(iso)
            if dt > now:
                return c
    return None
