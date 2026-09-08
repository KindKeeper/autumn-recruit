#!/usr/bin/env python3
"""migrate.py — 一次性迁移：jobhunt.db → data/companies/*.yml，并用 offershow 回填/验证 job_posted

用法: .venv/bin/python tools/migrate.py
产物: data/companies/*.yml（160 个岗位）、outputs/verification_report.md（核对报告，不入库）
原始 offershow 响应只缓存在 /tmp，不进仓库。
"""
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DB = Path.home() / "09-招聘信息系统/jobhunt.db"
OUT = ROOT / "data/companies"
REPORT = ROOT / "outputs/verification_report.md"
CACHE = Path("/tmp/offershow_company_cache.json")

STATUS_OUTCOME = {"未通过": "rejected", "已放弃": "given_up", "已冻结": "frozen", "已过期": "expired"}
NODE_COL = {"applied": "投递日", "assessment": "评测日", "written_test": "笔试日",
            "interview_1": "一面日", "interview_2": "二面日", "interview_more": "更多面日",
            "offer": "Offer日"}
W_MAP = [("fit", "W1"), ("track", "W2"), ("city", "W3"), ("salary", "W4"),
         ("stability", "W5"), ("certainty", "W6"), ("urgency", "W7"), ("wlb", "W8")]
GROUP_MAP = {"秋招提前批": "提前批", "秋招正式批": "正式批"}


def slug(s, n=48):
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", str(s)).strip("-")
    return s[:n] or "x"


def fetch_offershow(name):
    """按公司名搜校招信息表，返回 plans 列表（带缓存）"""
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
        plans = []
        print(f"  [warn] offershow 查询失败 {name}: {e}", file=sys.stderr)
    cache[name] = plans
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    time.sleep(0.35)
    return plans


def pick_announcement(plans, group=""):
    """优先匹配岗位批次的 2027届秋招公告（提前批/正式批），取最早；无则取最近一条"""
    if not plans:
        return None
    autumn = [p for p in plans if "2027" in p["recruit_title"]
              and any(k in p["recruit_title"] for k in ("秋招", "校园招聘", "校招"))]
    if group == "提前批":
        batch = [p for p in autumn if "提前批" in p["recruit_title"]]
    elif group == "正式批":
        batch = [p for p in autumn if "提前批" not in p["recruit_title"]]
    else:
        batch = []
    pool = batch or autumn or plans
    if pool is autumn or pool is plans:
        return sorted(pool, key=lambda p: p["create_time"])[-1] if pool is plans \
            else sorted(pool, key=lambda p: p["create_time"])[0]
    return sorted(pool, key=lambda p: p["create_time"])[0]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    jobs = conn.execute(
        "SELECT j.*, c.企业简称, c.企业全称, c.企业分类, c.校招入口 FROM jobs j "
        "JOIN companies c ON c.id=j.company_id").fetchall()

    # ---- offershow 匹配（按企业简称，miss 则用全称再试）----
    company_names = sorted({j["企业简称"] for j in jobs})
    print(f"== offershow 匹配 {len(company_names)} 家企业 ==")
    ann = {}
    misses = []
    for i, name in enumerate(company_names, 1):
        plans = fetch_offershow(name)
        if not plans:
            full = conn.execute("SELECT 企业全称 FROM companies WHERE 企业简称=?", (name,)).fetchone()
            if full and full[0] and full[0] != name:
                plans = fetch_offershow(full[0])
        if plans:
            ann[name] = plans
        else:
            misses.append(name)
        if i % 40 == 0:
            print(f"  进度 {i}/{len(company_names)}，命中 {len(ann)}")

    # ---- 生成 YAML ----
    used, n_backfill, n_skip_order = set(), 0, 0
    files = []
    for j in jobs:
        co = j["企业简称"]
        stages = {k: j[col] for k, col in NODE_COL.items() if j[col]}
        d = {
            "id": f"job-{j['id']:04d}",
            "name": co,
            "position": j["岗位名称"],
            "group": GROUP_MAP.get(j["招聘批次"], j["招聘批次"] or "正式批"),
            "channel": "官网",
            "city": j["主城市"] or j["工作地点"] or "",
            "link": j["投递链接"] or j["校招入口"] or "",
            "salary_range": j["薪资情况"] or "",
            "stages": stages,
            "updated_at": str(j["更新日期"])[:10],
        }
        if j["岗位分类"]:
            d["track"] = j["岗位分类"]
        if j["专业边界"]:
            d["boundary"] = j["专业边界"]
        if j["投递截止"]:
            d["apply_deadline"] = str(j["投递截止"])[:10]
        out = STATUS_OUTCOME.get(j["投递状态"])
        if out:
            d["outcome"] = out
        # offershow 回填 job_posted（公告早于投递日才可信）
        a = pick_announcement(ann.get(co) or [], d["group"])
        if a:
            applied = stages.get("applied")
            if applied and a["create_time"] > str(applied)[:10]:
                n_skip_order += 1
            else:
                d["job_posted"] = a["create_time"]
                d["source_id"] = f"offershow:{a['uuid']}"
                if a["recommend_code"]:
                    d["referral_code"] = a["recommend_code"]
                n_backfill += 1
        if j["W1"] is not None:
            d["score"] = {k: j[w] for k, w in W_MAP if j[w] is not None}
            if j["评分依据"]:
                d["score_rationale"] = j["评分依据"]
        iv = conn.execute("SELECT * FROM interviews WHERE job_id=?", (j["id"],)).fetchall()
        if iv:
            d["interviews"] = [{"round": r["轮次"] or "", "date": str(r["面试日期"])[:10],
                                "stuck": r["卡壳点"] or "", "cause": r["归因"] or "",
                                "result": r["结果"] or ""} for r in iv]
        nt = conn.execute("SELECT * FROM notes WHERE job_id=? ORDER BY 日期", (j["id"],)).fetchall()
        if nt:
            d["log"] = [{"date": str(r["日期"])[:10],
                         "note": f"[{r['类型']}] {r['内容']}"} for r in nt if r["内容"]]
        if j["备注"]:
            d["note"] = j["备注"]
        if j["企业分类"]:
            d["tags"] = [j["企业分类"]]

        fname = f"{slug(co)}-{slug(j['岗位名称'], 36)}.yml"
        while fname in used:
            fname = f"{slug(co)}-{slug(j['岗位名称'], 30)}-j{j['id']}.yml"
        used.add(fname)
        files.append((fname, d))

    for old in OUT.glob("*.yml"):
        old.unlink()
    for fname, d in files:
        (OUT / fname).write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8")

    # ---- 核对报告 ----
    matched_jobs = sum(1 for _, d in files if "job_posted" in d)
    lines = ["# 迁移核对报告\n",
             f"- 岗位总数: {len(files)}",
             f"- 企业命中 offershow: {len(ann)}/{len(company_names)}",
             f"- job_posted 回填: {matched_jobs}（公告晚于投递日被拒: {n_skip_order}）",
             f"- DB 原有发布日期: 0（该字段全空，offershow 为唯一来源）\n",
             "## 未命中企业（需手工补发布日期）\n"]
    lines += [f"- {m}" for m in misses]
    lines += ["\n## 命中明细\n", "| 企业 | 采用公告 | 公告日期 | 内推码 |", "|---|---|---|---|"]
    for co, plans in sorted(ann.items()):
        a = pick_announcement(plans) or {}
        lines.append(f"| {co} | {a.get('recruit_title','')} | {a.get('create_time','')} | {a.get('recommend_code') or '-'} |")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] 写出 {len(files)} 个 YAML；offershow 命中 {len(ann)}/{len(company_names)}；"
          f"回填 {matched_jobs}；报告 → outputs/verification_report.md")


if __name__ == "__main__":
    main()
