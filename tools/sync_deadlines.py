#!/usr/bin/env python3
"""sync_deadlines.py — 用 offershow 校验/更新待投递岗位的 apply_deadline

规则：
- offershow time_type==1（具体截止）→ 采用其 end_time 作为 apply_deadline
- offershow time_type==2（尽快投递/长期）→ 若现有截止已过，移除过期截止
- 每次修改写入 log 流水（git diff 可审计）
用法: .venv/bin/python tools/sync_deadlines.py [--apply]（默认 dry-run）
"""
import datetime
import glob
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date.today().isoformat()
CACHE = Path("/tmp/offershow_dl_cache.json")


def fetch(name):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if name in cache:
        return cache[name]
    body = urllib.parse.urlencode({"search_content": name}).encode()
    req = urllib.request.Request(
        "https://www.offershow.cn/api/od/plan_table?page=1&size=100",
        data=body, headers={"User-Agent": "Mozilla/5.0",
                            "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)["data"]
        plans = [{"company_name": p["company_name"], "create_time": p["create_time"][:10],
                  "recruit_title": p["recruit_title"], "time_type": p.get("time_type"),
                  "end_time": (p.get("end_time") or "")[:10],
                  "uuid": p["uuid"]} for p in (d.get("plans") or [])]
    except Exception as e:
        print(f"  [warn] 查询失败 {name}: {e}", file=sys.stderr)
        plans = []
    cache[name] = plans
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    time.sleep(0.35)
    return plans


IRRELEVANT_TOKENS = ["投资", "消金", "消费金融", "大使", "实习生", "实习招聘", "春季"]


def pick_dl(plans, query=""):
    """选截止公告：只看 2027 届相关公告(time_type=1)；优先未截止且最晚的，全过期则取最近截止的。
    剔除与查询实体无关的子品牌公告（如搜腾讯却命中腾讯投资）"""
    relevant = [p for p in plans if "2027" in p["recruit_title"]
                and p["time_type"] == 1 and p["end_time"]
                and not any(t in p["recruit_title"] and t not in query for t in IRRELEVANT_TOKENS)]
    if not relevant:
        return None
    future = [p for p in relevant if p["end_time"] >= TODAY]
    pool = future or relevant
    return sorted(pool, key=lambda p: p["end_time"])[-1]


def norm_name(s):
    """公司名规范化：去括号/英文/常见后缀，用于实体家族比较"""
    s = re.sub(r"[（(].*?[)）]", "", str(s))
    s = re.sub(r"[A-Za-z]+", "", s).lower().strip()
    for suf in ("有限责任公司", "股份有限公司", "有限公司", "公司", "集团", "股份",
                "科技", "有限", "控股", "技术", "电子", "信息", "数码", " "):
        s = s.replace(suf, "")
    return s


def is_ambiguous(query, plans):
    """结果公司名是否与查询词同一实体家族（规范化后前缀相容）"""
    q = norm_name(query)
    if not q:
        return False
    ents = {norm_name(p["company_name"]) for p in plans}
    return not any(e and (e.startswith(q) or q.startswith(e)) for e in ents)


def pick(plans):
    if not plans:
        return None
    autumn = [p for p in plans if "2027" in p["recruit_title"]
              and any(k in p["recruit_title"] for k in ("秋招", "校园招聘", "校招"))]
    if autumn:
        return sorted(autumn, key=lambda p: p["create_time"])[0]
    return sorted(plans, key=lambda p: p["create_time"])[-1]


def main():
    apply = "--apply" in sys.argv
    changes, skipped = [], []
    files = sorted(glob.glob(str(ROOT / "data/companies/*.yml")))
    for f in files:
        p = Path(f)
        rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if (rec.get("stages") or {}).get("applied") or rec.get("outcome"):
            continue  # 只看待投递
        co = rec.get("name", "")
        plans = fetch(co)
        if not plans:
            skipped.append(f"{co}: offershow 无记录")
            continue
        a = pick_dl(plans, co)
        old_dl = rec.get("apply_deadline", "")
        new_dl = a["end_time"] if a else ""
        modified = False
        ambiguous = is_ambiguous(co, plans)
        is_future = bool(new_dl and new_dl >= TODAY)
        if ambiguous:
            changes.append(f"[需人工确认-实体歧义] {co}·{rec.get('position','')}: "
                           f"{old_dl or '（空）'} → {new_dl or '尽快投递'}")
        elif new_dl and is_future:
            if new_dl != old_dl:
                changes.append(f"{co}·{rec.get('position','')}: {old_dl or '（空）'} → {new_dl}"
                               f"（依据: {a['recruit_title']}）")
                if apply:
                    rec["apply_deadline"] = new_dl
                    rec.setdefault("log", []).append(
                        {"date": TODAY, "note": f"[offershow] 截止更新为 {new_dl}（原 {old_dl or '空'}）"})
                    modified = True
        elif new_dl and not is_future:
            # 已截止的公告只报告不写入，避免把旧批次死线当事实
            changes.append(f"[需人工确认-已截止] {co}·{rec.get('position','')}: "
                           f"最近批次 {new_dl} 已截止（{a['recruit_title']}）")
        elif not new_dl and old_dl:
            try:
                expired = datetime.date.fromisoformat(str(old_dl)[:10]) < datetime.date.today()
            except ValueError:
                expired = False  # 非日期文本（如"尽快投递"）不处理
            if expired:
                changes.append(f"{co}·{rec.get('position','')}: 移除过期截止 {old_dl}（官方: 尽快投递）")
                if apply:
                    rec.pop("apply_deadline", None)
                    rec.setdefault("log", []).append(
                        {"date": TODAY, "note": f"[offershow] 原截止 {old_dl} 已过，官方长期有效，移除"})
                    modified = True
        if modified:
            p.write_text(yaml.safe_dump(rec, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")

    print(f"== {'APPLY' if apply else 'DRY-RUN'}：{len(changes)} 条截止变更，{len(skipped)} 家无记录 ==")
    for c in changes:
        print("  " + c)
    for s in skipped:
        print("  [skip] " + s)


if __name__ == "__main__":
    main()
