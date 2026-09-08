#!/usr/bin/env python3
"""sync_posted.py — 用 offershow 按岗位批次校正 job_posted（取批次内更新的公告）

规则：
- group=提前批 → 取标题含"提前批"的 2027 届秋招公告中最新一条
- group=正式批 → 取标题不含"提前批"的 2027 届秋招公告中最新一条
- 其他批次 → 2027 届秋招公告中最新一条
- 每次修改写入 log 流水
用法: .venv/bin/python tools/sync_posted.py [--apply]（默认 dry-run）
"""
import datetime
import re
import glob
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date.today().isoformat()
CACHE = Path("/tmp/offershow_company_cache.json")


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
                  "recruit_title": p["recruit_title"], "notice_url": p["notice_url"],
                  "recommend_code": p.get("recommend_code", ""),
                  "uuid": p["uuid"]} for p in (d.get("plans") or [])]
    except Exception as e:
        print(f"  [warn] 查询失败 {name}: {e}", file=sys.stderr)
        plans = []
    cache[name] = plans
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    time.sleep(0.35)
    return plans


def norm_name(s):
    s = re.sub(r"[（(].*?[)）]", "", str(s))
    s = re.sub(r"[A-Za-z]+", "", s).lower().strip()
    for suf in ("有限责任公司", "股份有限公司", "有限公司", "公司", "集团", "股份",
                "科技", "有限", "控股", "技术", "电子", "信息", "数码", " "):
        s = s.replace(suf, "")
    return s


BAN_TOKENS = ["投资", "消金", "消费金融", "大使", "实习生", "实习招聘", "春季", "抖音", "金融科技"]


def pick_posted(plans, query, group):
    """批次匹配 + 实体分级（ exact > 前缀相容 > 放弃）+ 子品牌公告剔除，取最新 """
    autumn = [p for p in plans if "2027" in p["recruit_title"]
              and any(k in p["recruit_title"] for k in ("秋招", "校园招聘", "校招"))
              and not any(t in p["recruit_title"] and t not in query for t in BAN_TOKENS)]
    if group == "提前批":
        autumn = [p for p in autumn if "提前批" in p["recruit_title"]]
    elif group == "正式批":
        autumn = [p for p in autumn if "提前批" not in p["recruit_title"]]
    if not autumn:
        return None
    q = norm_name(query)
    exact = [p for p in autumn if norm_name(p["company_name"]) == q]
    if exact:
        pool = exact
    else:
        pool = [p for p in autumn
                if (e := norm_name(p["company_name"])) and (e.startswith(q) or q.startswith(e))]
    if not pool:
        return None  # 实体家族对不上，不自动写入
    return sorted(pool, key=lambda p: p["create_time"])[-1]


def main():
    apply = "--apply" in sys.argv
    changes, misses = [], set()
    files = sorted(glob.glob(str(ROOT / "data/companies/*.yml")))
    for f in files:
        p = Path(f)
        rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        co = rec.get("name", "")
        plans = fetch(co)
        a = pick_posted(plans, co, rec.get("group", ""))
        if not a:
            if plans:
                misses.add(f"{co}: 无2027届秋招公告")
            else:
                misses.add(f"{co}: offershow无记录")
            continue
        old = str(rec.get("job_posted", ""))
        new = a["create_time"]
        if new != old:
            tag = {"提前批": "提前批", "正式批": "正式批"}.get(rec.get("group"), "秋招")
            changes.append(f"{co}·{rec.get('position','')}: {old or '（空）'} → {new} [{tag}]"
                           f"（{a['recruit_title']}）")
            if apply:
                rec["job_posted"] = new
                rec["source_id"] = f"offershow:{a['uuid']}"
                if a["recommend_code"]:
                    rec["referral_code"] = a["recommend_code"]
                rec.setdefault("log", []).append(
                    {"date": TODAY, "note": f"[offershow] {tag}公告发布 {new}（原 {old or '空'}）"})
                p.write_text(yaml.safe_dump(rec, allow_unicode=True, sort_keys=False),
                             encoding="utf-8")
    print(f"== {'APPLY' if apply else 'DRY-RUN'}：{len(changes)} 条 job_posted 变更 ==")
    for c in changes:
        print("  " + c)
    for m in sorted(misses):
        print("  [skip] " + m)


if __name__ == "__main__":
    main()
