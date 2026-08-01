"""AI 顶会信息抓取主脚本

读取 config.yml，抓取各会议官网 Dates 页，解析时间节点，
输出:
  - data/conferences.json   主数据
  - data/review.md          人工校验清单
  - js/data-inline.js       内联数据（保证双击离线可用）

用法:
  .venv/Scripts/python.exe scripts/scraper.py
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

# 让 parsers 包可导入
sys.path.insert(0, str(Path(__file__).parent))
from parsers import researchr, cvf, standalone
from ccf_supplement import supplement_entry, find_future_entry, parse_ccf_date, parse_ccf_deadline

AOE = timezone(timedelta(hours=-12))
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
JS_DIR = PROJECT_DIR / "js"

# 禁用系统代理直连。本机配置了本地代理 127.0.0.1:10808（代理客户端未运行时），
# requests 会自动拾取系统代理并挂起至超时；实测官网与 CDN 直连均正常，
# 故显式置空代理，避免被失效的本地代理拖垮抓取。
NO_PROXY = {"http": None, "https": None}

PARSERS = {"researchr": researchr, "cvf": cvf, "standalone": standalone}

# deadlines 的期望先后顺序(左 ≤ 右), 用于校验解析器是否把字段认错
DEADLINE_ORDER = [
    "abstract", "submission", "rebuttal_start",
    "rebuttal_end", "notification", "camera_ready",
]


def validate_ordering(entry):
    """校验 deadlines 的先后顺序; 倒挂的字段降为 low 并返回问题说明。

    期望 abstract ≤ submission ≤ rebuttal_start ≤ rebuttal_end
    ≤ notification ≤ camera_ready。解析器把字段认错(如 ICCV 曾把
    abstract/submission 颠倒)时, 日期会倒挂, 在这里被查出。
    """
    issues = []
    prev_field, prev_dt = None, None
    for field in DEADLINE_ORDER:
        iso = entry["deadlines"].get(field)
        if not iso:
            continue
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if prev_dt is not None and dt < prev_dt:
            # 前一字段比当前字段还晚 → 顺序倒挂, 两边都打成 low 待人工核对
            entry["confidence"][field] = "low"
            entry["confidence"][prev_field] = "low"
            issues.append(
                f"顺序异常: {prev_field}({prev_dt.date()}) 晚于 "
                f"{field}({dt.date()}) — 疑似字段错配, 请核对官网"
            )
        prev_field, prev_dt = field, dt
    return issues


def load_config():
    with open(SCRIPT_DIR / "config.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_utc():
    return datetime.now(timezone.utc)


def select_candidate_years(conf, now):
    """返回候选年份列表，按优先级排序（投稿未截止的优先，含最近过去届作 fallback）。"""
    year = now.year
    biennial = conf.get("biennial")
    if biennial == "odd":
        if year % 2 == 0:
            year += 1
        return [year, year + 2, year - 2]
    elif biennial == "even":
        if year % 2 == 1:
            year += 1
        return [year, year + 2, year - 2]
    else:
        return [year, year + 1, year - 1]


def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # 最多重试 3 次以容忍瞬态网络错误(如 RemoteDisconnected / 连接重置)。
    # 单次抖动可能导致整届抓取失败——ICCV 等 ccf 无未来届的会议没有回退, 会整体缺失。
    # 仅对连接异常重试; 4xx/5xx(如 404)是确定性"不存在", 直接返回不重试。
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=30, proxies=NO_PROXY)
            if r.status_code == 200:
                return r.text
            print(f"  [http {r.status_code}] {url}")
            return None
        except requests.exceptions.RequestException as e:
            if attempt < 2:
                time.sleep(1.5)
                continue
            print(f"  [fetch error] {e}")
            return None


def parse_with(parser_name, html, conf, year):
    parser = PARSERS.get(parser_name)
    if not parser:
        return None
    try:
        return parser.parse(html, conf, year)
    except Exception as e:
        print(f"  [parse error] {e}")
        return None


def build_entry(conf, year, url, parsed):
    """组装单个会议的最终数据条目。"""
    return {
        "id": f"{conf['id']}{str(year)[2:]}",
        "title": conf["title"],
        "full_name": conf["full_name"],
        "year": year,
        "category": conf["category"],
        "link": url.rsplit("/Dates", 1)[0] if "/Dates" in url else url,
        "place": parsed.get("place"),
        "conference_start": parsed.get("conference_start"),
        "conference_end": parsed.get("conference_end"),
        "timezone": "AoE",
        "deadlines": parsed.get("deadlines", {}),
        "confidence": parsed.get("confidence", {}),
        "source": url,
        "note": "",
    }


def build_ccf_entry(conf, year, ccf_conf):
    """从 ccf-deadlines 届次数据构建 entry。"""
    timeline = {}
    if ccf_conf.get("timeline"):
        timeline = ccf_conf["timeline"][0] if isinstance(ccf_conf["timeline"], list) else ccf_conf["timeline"]
    deadlines = {}
    confidence = {}
    if timeline.get("deadline"):
        iso = parse_ccf_deadline(timeline["deadline"])
        if iso:
            deadlines["submission"] = iso
            confidence["submission"] = "medium"
    if timeline.get("abstract_deadline"):
        iso = parse_ccf_deadline(timeline["abstract_deadline"])
        if iso:
            deadlines["abstract"] = iso
            confidence["abstract"] = "medium"
    start, end = parse_ccf_date(ccf_conf.get("date", ""), year)
    link = ccf_conf.get("link", "")
    return {
        "id": f"{conf['id']}{str(year)[2:]}",
        "title": conf["title"],
        "full_name": conf["full_name"],
        "year": year,
        "category": conf["category"],
        "link": link,
        "place": ccf_conf.get("place"),
        "conference_start": start,
        "conference_end": end,
        "timezone": "AoE",
        "deadlines": deadlines,
        "confidence": confidence,
        "source": link or "ccf-deadlines",
        "note": "数据来源: ccf-deadlines",
    }


def scrape_conference(conf, now):
    """抓取单个会议，返回 (entry_or_None, review_notes_list)。"""
    parser_name = conf["parser"]
    candidates = select_candidate_years(conf, now)
    notes = []
    fallback_entry = None

    for year in candidates:
        yy = str(year)[2:]
        url = conf["url_template"].format(year=year, yy=yy)
        print(f"  [{conf['title']}] 尝试 {year}: {url}")
        html = fetch(url)
        if not html:
            notes.append(f"{conf['title']} {year}: 页面抓取失败 ({url})")
            continue
        parsed = parse_with(parser_name, html, conf, year)
        if not parsed or not parsed.get("deadlines"):
            notes.append(f"{conf['title']} {year}: 解析无结果 ({url})")
            continue

        sub = parsed["deadlines"].get("submission")
        if sub:
            sub_dt = datetime.fromisoformat(sub)
            if sub_dt > now:
                print(f"  -> 选中 {year}（投稿未截止）")
                entry = build_entry(conf, year, url, parsed)
                supplement_entry(entry, conf["id"])
                return entry, notes
            else:
                print(f"  -> {year} 投稿已截止，尝试下一年")
                # 回退取"最近一届"(年份最大)而非首个遇到的已截止届:
                # 候选顺序为 [year, year+1, year-1], year+1 若存在且已截止才是最近的。
                if fallback_entry is None or year > fallback_entry["year"]:
                    fallback_entry = build_entry(conf, year, url, parsed)
                notes.append(f"{conf['title']} {year}: 投稿已截止 ({sub[:10]})")
                continue
        else:
            print(f"  -> 选中 {year}（无 submission 字段，直接采用）")
            entry = build_entry(conf, year, url, parsed)
            supplement_entry(entry, conf["id"])
            return entry, notes

    # 官网候选用完，检查 ccf-deadlines 是否有投稿未截止的未来届
    base_year = fallback_entry["year"] if fallback_entry else now.year - 1
    future = find_future_entry(conf["id"], base_year, now)
    if future:
        year = int(future["year"])
        print(f"  -> ccf-deadlines 发现未来届 {year}（投稿未截止）")
        entry = build_ccf_entry(conf, year, future)
        notes.append(f"{conf['title']}: 官网无未来届，从 ccf-deadlines 采用 {year}")
        return entry, notes

    if fallback_entry:
        notes.append(f"{conf['title']}: 所有候选投稿已截止，采用最近一届 {fallback_entry['year']}")
        supplement_entry(fallback_entry, conf["id"])
        return fallback_entry, notes

    notes.append(f"{conf['title']}: 所有候选年份均抓取失败，需人工补录")
    return None, notes


def generate_review(entries, all_notes, now):
    """生成人工校验清单 review.md。"""
    lines = [f"# 待人工校验 - {now.strftime('%Y-%m-%d %H:%M')} 生成\n"]
    has_issue = False

    for entry, notes in zip(entries, all_notes):
        if entry is None:
            continue
        issues = list(notes)
        # 检查缺失字段
        missing = [
            k for k in ("submission", "notification", "conference_start")
            if not entry["deadlines"].get(k) and k != "conference_start"
        ]
        if not entry.get("conference_start"):
            missing.append("conference_start")
        if not entry.get("place"):
            missing.append("place")
        # 检查低置信度字段
        low_conf = [
            k for k, v in entry["confidence"].items()
            if v in ("medium", "low", "missing")
        ]
        if missing:
            issues.append(f"缺失字段: {', '.join(missing)}")
            has_issue = True
        if low_conf:
            issues.append(f"待确认字段: {', '.join(low_conf)}")
            has_issue = True

        if issues:
            lines.append(f"\n## {entry['title']} {entry['year']}\n")
            for it in issues:
                lines.append(f"- {it}")
            lines.append(f"- 数据来源: {entry['source']}")

    # 失败的会议
    for entry, notes in zip(entries, all_notes):
        if entry is None and notes:
            has_issue = True
            lines.append(f"\n## 抓取失败\n")
            for it in notes:
                lines.append(f"- {it}")

    if not has_issue:
        lines.append("\n所有会议数据均正常，无需人工干预。\n")
    return "\n".join(lines)


def generate_inline_js(data):
    """生成 js/data-inline.js，保证 file:// 协议双击可用。"""
    return f"window.CONF_DATA = {json.dumps(data, ensure_ascii=False, indent=2)};\n"


def main():
    now = now_utc()
    print(f"=== 开始抓取 {now.strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    config = load_config()
    entries = []
    all_notes = []

    for conf in config["conferences"]:
        print(f"\n--- {conf['title']} ---")
        entry, notes = scrape_conference(conf, now)
        if entry:
            notes.extend(validate_ordering(entry))
        entries.append(entry)
        all_notes.append(notes)

    # 过滤掉 None，但保留顺序信息用于 review
    valid_entries = [e for e in entries if e]

    output = {
        "generated_at": now.isoformat(),
        "conferences": valid_entries,
    }

    # 写 conferences.json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "conferences.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 data/conferences.json（{len(valid_entries)} 个会议）")

    # 写 review.md
    review = generate_review(entries, all_notes, now)
    with open(DATA_DIR / "review.md", "w", encoding="utf-8") as f:
        f.write(review)
    print("已写入 data/review.md")

    # 写 data-inline.js
    JS_DIR.mkdir(parents=True, exist_ok=True)
    with open(JS_DIR / "data-inline.js", "w", encoding="utf-8") as f:
        f.write(generate_inline_js(output))
    print("已写入 js/data-inline.js")

    print(f"\n=== 完成 ===")
    print(f"成功: {len(valid_entries)}/{len(config['conferences'])}")
    if len(valid_entries) < len(config["conferences"]):
        print("部分会议抓取失败，请查看 data/review.md")


if __name__ == "__main__":
    main()
