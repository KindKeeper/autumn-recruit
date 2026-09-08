#!/usr/bin/env python3
"""build.py — 校验数据 → 推导阶段/评分 → 生成单文件看板 dist/index.html

用法: .venv/bin/python build.py
校验失败会以非零退出，作为 CI 的数据质量门禁。
"""
import datetime
import glob
import json
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Template

ROOT = Path(__file__).parent
TODAY = datetime.date.today()

# ---------- 隐私预检（public 仓库红线） ----------
PRIVACY_PATTERNS = [
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
]

REQUIRED_FIELDS = ["id", "name", "position", "updated_at"]


def fail(msg):
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def parse_date(s):
    return datetime.date.fromisoformat(str(s)[:10])


def load_config():
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
    cfg["stage_keys"] = [s["key"] for s in cfg["stages"]]
    cfg["stage_labels"] = {s["key"]: s["label"] for s in cfg["stages"]}
    cfg["outcome_labels"] = {o["key"]: o["label"] for o in cfg["outcomes"]}
    if sum(cfg["score_weights"].values()) != 100:
        fail("config.yml: score_weights 权重之和必须等于 100")
    return cfg


def validate_and_build(rec, cfg, fname):
    rid = rec.get("id", fname)
    for f in REQUIRED_FIELDS:
        if f not in rec:
            fail(f"{rid}: 缺少必填字段 {f}")

    for label, pat in PRIVACY_PATTERNS:
        for s in walk_strings(rec):
            if pat.search(s):
                fail(f"{rid}: 隐私红线——检测到疑似{label}: {s[:20]}*** 请删除后再构建")

    stages = rec.get("stages") or {}
    for k in stages:
        if k not in cfg["stage_keys"]:
            fail(f"{rid}: stages 含非法节点 '{k}'（只能用七节点枚举）")
    if stages.get("interview_2") and not stages.get("interview_1"):
        fail(f"{rid}: 单调性——有 interview_2 必须先有 interview_1")
    if stages.get("offer") and not stages.get("interview_1"):
        fail(f"{rid}: 单调性——有 offer 至少要有 interview_1")

    outcome = rec.get("outcome")
    if outcome and outcome not in cfg["outcome_labels"]:
        fail(f"{rid}: outcome 非法 '{outcome}'")

    job_posted = rec.get("job_posted")
    for k, v in stages.items():
        d = parse_date(v["date"] if isinstance(v, dict) else v)
        if job_posted and d < parse_date(job_posted):
            fail(f"{rid}: 节点 {k} 早于 job_posted")
        if d > TODAY + datetime.timedelta(days=1):
            fail(f"{rid}: 节点 {k} 日期在未来，请检查")

    score = rec.get("score") or {}
    for k, v in score.items():
        if k not in cfg["score_weights"]:
            fail(f"{rid}: score 含非法子项 '{k}'")
        if not (0 <= int(v) <= 10):
            fail(f"{rid}: score.{k} 必须在 0-10 之间")

    # ---- 推导阶段 ----
    reached = [k for k in cfg["stage_keys"] if stages.get(k)]
    if not stages.get("applied"):
        stage_key, stage_label = "pending", "待投递"
    else:
        stage_key = reached[-1]
        stage_label = "已" + cfg["stage_labels"][stage_key]

    # ---- 评分 ----
    w = cfg["score_weights"]
    subs = {k: int(score.get(k, 0)) for k in w}
    if cfg["score_mode"] == "expected":
        w_others = {k: x for k, x in w.items() if k != "odds"}
        att = sum(subs[k] * x for k, x in w_others.items()) / sum(w_others.values()) * 10
        total = att * subs["odds"] / 10
    else:
        total = sum(subs[k] * x for k, x in w.items()) / 10
    total = round(total, 1)
    tiers = sorted(cfg["priority_tiers"].items(), key=lambda kv: -kv[1])
    tier = next((t for t, th in tiers if total >= th), "D")

    deadline = rec.get("apply_deadline")
    urgent = bool(deadline and not outcome and stages.get("applied")
                  and 0 <= (parse_date(deadline) - TODAY).days <= 7)

    return {
        "id": rid, "name": rec["name"], "position": rec["position"],
        "city": rec.get("city", ""), "channel": rec.get("channel", ""),
        "group": rec.get("group", ""), "link": rec.get("link", ""),
        "salary_range": rec.get("salary_range", ""),
        "job_posted": str(job_posted or ""), "deadline": str(deadline or ""),
        "stage_key": stage_key, "stage_label": stage_label,
        "outcome": outcome or "", "outcome_label": cfg["outcome_labels"].get(outcome, ""),
        "score_total": total, "tier": tier, "subs": subs,
        "urgent": urgent, "note": rec.get("note", ""), "tags": rec.get("tags") or [],
        "reached": reached,
    }


HTML = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>秋招投递看板</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2430;--sub:#8a90a0;--line:#e6e8ee;
--A:#b8860b;--B:#2563eb;--C:#64748b;--D:#a8aebb;
--win:#15803d;--lose:#b91c1c;--idle:#a16207}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding:16px;max-width:1400px;margin:0 auto}
h1{font-size:20px;margin-bottom:4px}
h2{font-size:15px;margin:24px 0 10px}
.meta{color:var(--sub);font-size:12px;margin-bottom:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.stat b{display:block;font-size:22px}
.stat span{color:var(--sub);font-size:12px}
.funnel div{display:flex;align-items:center;gap:8px;margin:4px 0}
.funnel .bar{height:18px;border-radius:4px;background:linear-gradient(90deg,#4f8cff,#2563eb);min-width:4px}
.funnel .n{width:32px;text-align:right;font-variant-numeric:tabular-nums}
.funnel .t{width:64px;color:var(--sub);font-size:12px}
.board{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(230px,1fr);gap:10px;overflow-x:auto;padding-bottom:8px}
.col{background:#eef0f4;border-radius:10px;padding:8px;min-height:80px}
.col h3{font-size:13px;color:var(--sub);margin:2px 4px 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px}
.card .co{font-weight:600}
.card .pos{font-size:12px;color:var(--sub)}
.card .row{display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap}
.badge{font-size:11px;border-radius:4px;padding:1px 6px;color:#fff}
.dead{color:var(--lose);font-size:11px;font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;white-space:nowrap}
th{background:#eef0f4;color:var(--sub);font-weight:500}
td.sub{color:var(--sub)}
.warn{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:8px 12px;margin:6px 0;font-size:13px}
a{color:#2563eb;text-decoration:none}
</style>
</head>
<body>
<h1>秋招投递看板</h1>
<div class="meta">更新于 {{ today }} · 评分模式 {{ mode }} · 档位阈值 A≥{{ tA }} / B≥{{ tB }} / C≥{{ tC }}</div>

<h2>总览</h2>
<div class="stats">
{% for s in stats %}<div class="stat"><b>{{ s.v }}</b><span>{{ s.k }}</span></div>{% endfor %}
</div>

{% if urgent %}
<h2>临期提醒（7 天内截止）</h2>
{% for u in urgent %}<div class="warn">「{{ u.name }} · {{ u.position }}」网申 {{ u.deadline }} 截止，当前阶段：{{ u.stage_label }}</div>{% endfor %}
{% endif %}

<h2>投递漏斗（七节点）</h2>
<div class="funnel">
{% for f in funnel %}<div><span class="t">{{ f.label }}</span><span class="bar" style="width:{{ f.w }}%"></span><span class="n">{{ f.n }}</span></div>{% endfor %}
</div>

<h2>阶段看板</h2>
<div class="board">
{% for col in board %}
<div class="col"><h3>{{ col.label }}（{{ col.cards|length }}）</h3>
{% for c in col.cards %}
<div class="card">
  <div class="co">{% if c.link %}<a href="{{ c.link }}">{{ c.name }}</a>{% else %}{{ c.name }}{% endif %}</div>
  <div class="pos">{{ c.position }}{% if c.city %} · {{ c.city }}{% endif %}</div>
  <div class="row">
    <span class="badge" style="background:var(--{{ c.tier }})">{{ c.tier }} · {{ c.score_total }}</span>
    {% if c.outcome_label %}<span class="badge" style="background:var(--{{ 'win' if c.outcome=='signed' else 'lose' if c.outcome=='rejected' else 'idle' }})">{{ c.outcome_label }}</span>{% endif %}
    {% if c.urgent %}<span class="dead">截止 {{ c.deadline }}</span>{% endif %}
  </div>
</div>
{% endfor %}
</div>
{% endfor %}
</div>

<h2>优先级总表（按评分排序）</h2>
<table><tr><th>公司</th><th>岗位</th><th>城市</th><th>阶段</th><th>档位</th><th>总分</th>
{% for k in subkeys %}<th class="sub">{{ k }}</th>{% endfor %}<th>截止</th></tr>
{% for c in ranked %}
<tr>
<td>{% if c.link %}<a href="{{ c.link }}">{{ c.name }}</a>{% else %}{{ c.name }}{% endif %}</td>
<td>{{ c.position }}</td><td class="sub">{{ c.city }}</td><td>{{ c.stage_label }}{{ '（'+c.outcome_label+'）' if c.outcome_label }}</td>
<td><span class="badge" style="background:var(--{{ c.tier }})">{{ c.tier }}</span></td>
<td><b>{{ c.score_total }}</b></td>
{% for k in subkeys %}<td class="sub">{{ c.subs[k] }}</td>{% endfor %}
<td class="sub">{{ c.deadline }}</td>
</tr>
{% endfor %}
</table>
</body></html>
""")


def main():
    cfg = load_config()
    files = sorted(glob.glob(str(ROOT / "data/companies/*.yml")))
    if not files:
        fail("data/companies/ 下没有数据文件")
    recs = []
    for f in files:
        rec = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        recs.append(validate_and_build(rec, cfg, Path(f).name))

    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    applied = [r for r in recs if r["stage_key"] != "pending"]
    stats = [
        {"k": "待投递", "v": len(recs) - len(applied)},
        {"k": "已投递", "v": len(applied)},
        {"k": "offer/OC", "v": sum(1 for r in recs if r["stage_key"] == "offer")},
        {"k": "已挂", "v": sum(1 for r in recs if r["outcome"] == "rejected")},
        {"k": "泡池子", "v": sum(1 for r in recs if r["outcome"] == "pool")},
        {"k": "A 档在投", "v": sum(1 for r in applied if r["tier"] == "A" and not r["outcome"])},
    ]
    funnel, mx = [], max(1, len(applied))
    for s in cfg["stages"]:
        n = sum(1 for r in recs if s["key"] in r["reached"])
        funnel.append({"label": s["label"], "n": n, "w": max(2, round(n / mx * 100))})

    pending_items = sorted((r for r in recs if r["stage_key"] == "pending"),
                           key=lambda r: (tier_order[r["tier"]], -r["score_total"]))
    board = [{"label": "待投递", "cards": pending_items}]
    for s in cfg["stages"]:
        items = sorted((r for r in recs if r["stage_key"] == s["key"]),
                       key=lambda r: (tier_order[r["tier"]], -r["score_total"]))
        board.append({"label": "已" + s["label"], "cards": items})

    ranked = sorted(recs, key=lambda r: (-r["score_total"], tier_order[r["tier"]]))
    html = HTML.render(
        today=TODAY.isoformat(), mode=cfg["score_mode"],
        tA=cfg["priority_tiers"]["A"], tB=cfg["priority_tiers"]["B"], tC=cfg["priority_tiers"]["C"],
        stats=stats, funnel=funnel, board=board, ranked=ranked,
        subkeys=list(cfg["score_weights"].keys()),
        urgent=[r for r in recs if r["urgent"]],
    )
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"[OK] {len(recs)} 条记录 -> dist/index.html")


if __name__ == "__main__":
    main()
