#!/usr/bin/env python3
"""build.py — 校验数据 → 推导阶段/评分 → 生成多页面看板 dist/

页面: index.html(总览) rank.html(候选榜) pipeline.html(推进中) ended.html(已结束)
用法: .venv/bin/python build.py
校验失败以非零退出，作为 CI 数据质量门禁。
"""
import datetime
import glob
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from jinja2 import Template

ROOT = Path(__file__).parent
TODAY = datetime.date.today()

PRIVACY_PATTERNS = [
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
]
REQUIRED_FIELDS = ["id", "name", "position", "updated_at"]

STAGE_PILL = {"applied": "st-applied", "assessment": "st-assess", "written_test": "st-exam",
              "interview_1": "st-interview", "interview_2": "st-interview2",
              "interview_more": "st-interview3", "offer": "done"}


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
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


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
        if d is None:
            fail(f"{rid}: 节点 {k} 日期非法 '{v}'（须 YYYY-MM-DD）")
        if job_posted and parse_date(job_posted) and d < parse_date(job_posted):
            fail(f"{rid}: 节点 {k} 早于 job_posted")
        if d > TODAY + datetime.timedelta(days=1):
            fail(f"{rid}: 节点 {k} 日期在未来，请检查")

    score = rec.get("score") or {}
    for k, v in score.items():
        if k not in cfg["score_weights"]:
            fail(f"{rid}: score 含非法子项 '{k}'")
        if not (0 <= int(v) <= 10):
            fail(f"{rid}: score.{k} 必须在 0-10 之间")

    reached = [k for k in cfg["stage_keys"] if stages.get(k)]
    if not stages.get("applied"):
        stage_key, stage_label = "pending", "待投递"
    else:
        stage_key = reached[-1]
        stage_label = "已" + cfg["stage_labels"][stage_key]

    w = cfg["score_weights"]
    subkeys = list(w.keys())
    subs = {k: int(score.get(k, 0)) for k in subkeys}
    scored = bool(score)
    if scored:
        if cfg["score_mode"] == "expected":
            if "odds" not in w:
                fail("config: expected 模式要求 score_weights 含 odds 子项")
            w_others = {k: x for k, x in w.items() if k != "odds"}
            att = sum(subs[k] * x for k, x in w_others.items()) / sum(w_others.values()) * 10
            total = att * subs["odds"] / 10
        else:
            total = sum(subs[k] * x for k, x in w.items()) / 10
        total = round(total, 1)
        tiers = sorted(cfg["priority_tiers"].items(), key=lambda kv: -kv[1])
        tier = next((t for t, th in tiers if total >= th), "D")
    else:
        total, tier = None, None

    deadline = rec.get("apply_deadline")
    _dl = parse_date(deadline) if deadline else None
    urgent = bool(_dl and not outcome and stages.get("applied")
                  and 0 <= (_dl - TODAY).days <= 7)

    last_node_date = None
    for k in reversed(reached):
        last_node_date = parse_date(stages[k]["date"] if isinstance(stages[k], dict) else stages[k])
        if last_node_date:
            break

    return {
        "id": rid, "name": rec["name"], "position": rec["position"],
        "city": rec.get("city", ""), "group": rec.get("group", ""),
        "link": rec.get("link", ""), "track": rec.get("track", ""),
        "boundary": rec.get("boundary", ""),
        "salary_range": rec.get("salary_range", ""),
        "job_posted": str(job_posted or ""), "deadline": str(deadline or ""),
        "stage_key": stage_key, "stage_label": stage_label,
        "outcome": outcome or "", "outcome_label": cfg["outcome_labels"].get(outcome, ""),
        "outcome_note": rec.get("outcome_note", ""),
        "score_total": total, "tier": tier, "subs": subs, "sublist": [subs[k] for k in subkeys],
        "scored": scored, "urgent": urgent,
        "note": rec.get("note", ""), "tags": rec.get("tags") or [],
        "reached": reached, "last_node_date": last_node_date.isoformat() if last_node_date else "",
        "updated_at": str(rec.get("updated_at", ""))[:10],
        "interviews": rec.get("interviews") or [],
        "log": rec.get("log") or [],
    }


# ================= CSS / JS（沿用 jobhunt dashboard 设计） =================

CSS = """
  html[data-theme="light"] {
    --bg:#f4f6fb; --panel:#fff; --panel2:#eef1f8; --text:#1a2333; --muted:#64748b;
    --accent:#2563eb; --green:#0e9f6e; --red:#dc2626; --yellow:#d97706;
    --border:#dbe2ef; --rowhover:#f0f4fc; --rowborder:#e6ebf5; --purple:#7c3aed;
    --orange:#c9642a; --orange2:#c04a2e;
  }
  :root {
    --bg:#12151d; --panel:#1b1f2a; --panel2:#232836; --text:#e2e7f2; --muted:#8b93a7;
    --accent:#4d8dff; --green:#2fce8f; --red:#f26d6d; --yellow:#e8a33d;
    --border:#2c3244; --rowhover:#222839; --rowborder:#262c3d; --purple:#a879f0;
    --orange:#e08a4d; --orange2:#e06e4d;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font:14px/1.6 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;padding-bottom:60px;transition:background .25s,color .25s}
  header{background:var(--panel);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;align-items:center;gap:20px;position:sticky;top:0;z-index:10}
  header h1{font-size:20px;font-weight:700;white-space:nowrap}
  header h1 span{color:var(--accent)}
  nav{display:flex;gap:6px;flex:1;flex-wrap:wrap}
  nav a{background:transparent;border:1px solid var(--border);color:var(--muted);padding:7px 16px;border-radius:8px;cursor:pointer;font-size:14px;text-decoration:none;transition:.15s}
  nav a.active{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
  nav a:hover{border-color:var(--accent);color:var(--text)}
  .theme-toggle{background:var(--panel2);border:1px solid var(--border);color:var(--text);width:40px;height:40px;border-radius:10px;cursor:pointer;font-size:18px}
  main{max-width:1320px;margin:24px auto;padding:0 28px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-bottom:20px}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:15px 18px}
  .card .num{font-size:26px;font-weight:700}
  .card .lbl{color:var(--muted);font-size:13px;margin-top:2px}
  .card .num.green{color:var(--green)} .card .num.yellow{color:var(--yellow)} .card .num.red{color:var(--red)}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:18px}
  .panel h3{font-size:15px;margin-bottom:14px}
  .panel h3 .sub{font-weight:normal;color:var(--muted);font-size:12px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th{text-align:left;color:var(--muted);font-weight:500;padding:8px 10px;border-bottom:1px solid var(--border);font-size:12px;white-space:nowrap}
  td{padding:9px 10px;border-bottom:1px solid var(--rowborder)}
  tr:hover td{background:var(--rowhover)}
  .rank{font-weight:700;width:34px}
  .rank.r1{color:var(--yellow);font-size:16px}
  .rank.r3{color:var(--orange)}
  .score{font-weight:700;color:var(--accent);white-space:nowrap}
  .pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11.5px;background:var(--panel2);color:var(--muted);white-space:nowrap;border:1px solid var(--border)}
  .pill.st-applied{background:rgba(53,201,142,.15);color:var(--green);border-color:rgba(53,201,142,.4)}
  .pill.st-assess{background:rgba(165,106,232,.16);color:var(--purple);border-color:rgba(165,106,232,.45)}
  .pill.st-exam{background:rgba(77,163,255,.15);color:var(--accent);border-color:rgba(77,163,255,.45)}
  .pill.st-interview{background:rgba(255,200,87,.18);color:var(--yellow);border-color:rgba(255,200,87,.5)}
  .pill.st-interview2{background:rgba(224,138,77,.18);color:var(--orange);border-color:rgba(224,138,77,.5)}
  .pill.st-interview3{background:rgba(224,110,77,.18);color:var(--orange2);border-color:rgba(224,110,77,.5)}
  .pill.done{background:rgba(255,107,107,.14);color:var(--red);border-color:rgba(255,107,107,.4)}
  .pill.warn{background:rgba(255,200,87,.14);color:var(--yellow);border-color:rgba(255,200,87,.4)}
  .sub{color:var(--muted);font-size:12px}
  .meter{display:block;height:5px;width:100%;background:var(--panel2);border-radius:3px;margin-top:4px;overflow:hidden;max-width:110px}
  .meter i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,#2e7bb6,var(--accent))}
  .wc{display:inline-flex;gap:2px;vertical-align:middle}
  .wc i{width:13px;height:16px;border-radius:2px;background:var(--panel2);position:relative;overflow:hidden}
  .wc i b{position:absolute;bottom:0;left:0;right:0;background:linear-gradient(180deg,var(--accent),#3b82f6);border-radius:1px}
  .wc i b.low{background:var(--yellow)} .wc i b.low2{background:var(--red)}
  .wlegend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-bottom:12px;padding:10px 14px;background:var(--panel2);border-radius:8px;font-size:12px;color:var(--muted)}
  .wlegend b{color:var(--text);font-weight:600;margin-right:3px}
  .wlegend .s{color:var(--accent);font-weight:600;margin:0 2px}
  .table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .dist-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:13px}
  .dist-row .k{width:120px;color:var(--muted);white-space:nowrap}
  .dist-row .dbar{flex:1;height:16px;background:var(--panel2);border-radius:6px;overflow:hidden}
  .dist-row .dbar i{display:block;height:100%;border-radius:6px}
  .dist-row .n{width:44px;text-align:right;font-weight:600}
  .pipe-stage{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin-bottom:16px}
  .pipe-stage h3{font-size:15px;margin-bottom:4px}
  .pipe-stage .cnt{color:var(--muted);font-size:12px;margin-bottom:10px}
  .pipe-stage.empty-stage{opacity:.55;border-style:dashed}
  .pipe-item{padding:10px 4px;border-bottom:1px dashed var(--border)}
  .pipe-item:last-child{border-bottom:none}
  .deadline{color:var(--yellow);font-weight:600}
  .note{color:var(--muted);font-size:12.5px;margin-top:3px}
  .tag{display:inline-block;padding:1px 8px;border-radius:12px;font-size:11px;background:var(--panel2);color:var(--muted);border:1px solid var(--border);margin-right:6px}
  input,select{background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 12px;font-size:13.5px;outline:none}
  .toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
  .btn{background:var(--accent);color:#fff;border:none;padding:8px 20px;border-radius:8px;cursor:pointer;font-weight:600;font-size:13.5px}
  .empty{color:var(--muted);text-align:center;padding:30px}
  .foot{color:var(--muted);text-align:center;font-size:12px;margin-top:20px}
  .expandable{cursor:pointer}
  .expandable .caret{display:inline-block;transition:transform .2s;color:var(--muted);font-size:11px}
  .expandable.open .caret{transform:rotate(90deg)}
  .subrow td{background:var(--panel2)!important;padding:10px 14px;font-size:13px}
  .warn-box{background:rgba(255,107,107,.08);border:1px solid rgba(255,107,107,.3);border-radius:8px;padding:8px 12px;margin:6px 0;font-size:13px}
"""

JS_COMMON = """
function esc(s){return (s==null?"":String(s)).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
const themeBtn=document.getElementById("themeBtn");
function applyTheme(t){document.documentElement.setAttribute("data-theme",t);themeBtn.textContent=t==="light"?"\\u2600\\uFE0F":"\\u263E";}
themeBtn.addEventListener("click",()=>{applyTheme(document.documentElement.getAttribute("data-theme")==="light"?"dark":"light");});
applyTheme(window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");
"""

# 新鲜度/停滞徽章 + 截止 + W柱 等（数据内嵌渲染用）
JS_WIDGETS = """
function freshHue(days){const s=[[0,150],[14,45],[30,20],[45,0]];days=Math.max(0,days);if(days>=45)return 0;
  for(let i=1;i<s.length;i++){if(days<=s[i][0]){const[x0,h0]=s[i-1],[x1,h1]=s[i];return h0+(h1-h0)*((days-x0)/(x1-x0));}}return 0;}
function pill(text,bg,title){return `<span class="pill" style="background:${bg};color:#fff;border-color:${bg};font-weight:600" title="${esc(title||"")}">${text}</span>`;}
function freshBadge(pub){
  if(!pub)return pill("首发未知","hsl(220,12%,52%)","发布时间未记录");
  const t=new Date(pub).getTime();if(isNaN(t))return"";
  const days=Math.max(0,Math.floor((Date.now()-t)/86400000));
  const hue=Math.round(freshHue(days));
  let lab=days<=7?`新上架 ${days} 天`:(days<=14?`已搁置 ${days} 天`:`拖延 ${days} 天`);
  return pill(lab,`hsl(${hue},92%,45%)`,`首发 ${pub}`);
}
function progBadge(lastDate){
  if(!lastDate)return pill("进度未知","hsl(220,12%,52%)","最近进度未记录");
  const days=Math.max(0,Math.floor((Date.now()-new Date(lastDate).getTime())/86400000));
  const hue=Math.round(freshHue(days));
  const lab=days<=3?`${days} 天前推进`:`${days} 天未推进`;
  return pill(lab,`hsl(${hue},92%,45%)`,days<=3?"进度新鲜":(days<=10?"进度放缓，建议主动跟进":"长期停滞，需要立刻推动"));
}
function dlCell(dl){
  if(!dl)return `<span class="sub">—</span>`;
  const d=Math.ceil((new Date(dl)-Date.now())/86400000);
  if(isNaN(d))return `<span class="sub">${esc(dl)}</span>`;
  if(d<0)return `<span class="pill warn">已截止</span>`;
  return `<span class="deadline ${d<=5?"":""}">剩${d}天 <span class="sub">${esc(dl)}</span></span>`;
}
function scoreCell(j){
  if(!j.scored)return `<span class="sub">未评分</span>`;
  return `<span class="score">${j.total.toFixed(1)}</span><span class="meter"><i style="width:${j.total}%"></i></span>`;
}
function wBars(j){
  const h=`<span class="wc" title="${W_LBL.map((n,i)=>`${n} ${W_W[i]}% = ${j.subs[i]||0}/10`).join("｜")}">`;
  let s=h;for(let i=0;i<W_LBL.length;i++){const v=j.subs[i]||0;const lv=v>=8?"":(v>=5?"low":"low2");
    s+=`<i><b class="${lv}" style="height:${v*10}%"></b></i>`;}
  return s+"</span>";
}
function tierPill(j){
  if(!j.scored)return `<span class="pill">未评分</span>`;
  const colors={A:"var(--yellow)",B:"var(--accent)",C:"var(--muted)",D:"var(--muted)"};
  return `<span class="pill" style="background:${colors[j.tier]||"var(--muted)"};color:#fff;border-color:${colors[j.tier]||"var(--muted)"}">${j.tier} · ${j.total.toFixed(1)}</span>`;
}
function jobLine(j,extra){
  return `<div class="pipe-item"><b>${esc(j.name)}</b> · ${esc(j.position)} ${extra||""}
    <div class="note">${j.deadline?`截止 ${esc(j.deadline)} · `:""}${j.city?esc(j.city)+" · ":""}${j.updated_at?("更新 "+esc(j.updated_at)):""}${j.note?` · ${esc(j.note)}`:""}</div></div>`;
}
"""

BASE = Template("""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} · 秋招看板</title>
<style>""" + CSS + """</style>
</head>
<body>
<header>
  <h1>秋招<span>看板</span></h1>
  <nav>
    <a href="index.html" class="{{ 'active' if page=='index' }}">总览</a>
    <a href="rank.html" class="{{ 'active' if page=='rank' }}">候选榜</a>
    <a href="pipeline.html" class="{{ 'active' if page=='pipeline' }}">推进中</a>
    <a href="ended.html" class="{{ 'active' if page=='ended' }}">已结束</a>
  </nav>
  <button class="theme-toggle" id="themeBtn" title="切换主题">☾</button>
</header>
<main>
""" + "{{ content | safe }}" + """
<div class="foot">更新于 {{ today }} · 评分模式 {{ mode }} · 数据源 data/companies/*.yml（git 备份）</div>
</main>
<script>
const W_LBL = {{ w_lbl | safe }};
const W_W = {{ w_w | safe }};
""" + JS_COMMON + JS_WIDGETS + """
{{ script | safe }}
</script>
</body></html>
""")


def page(page_name, title, content, script, cfg, today, mode):
    w_lbl = [k for k in cfg["score_weights"]]
    w_w = list(cfg["score_weights"].values())
    return BASE.render(page=page_name, title=title, content=content, script=script,
                       w_lbl=w_lbl, w_w=w_w, today=today, mode=mode)


# ================= 页面模板 =================

INDEX_CONTENT = """
<div class="cards" id="stat-cards"></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px" class="idx-grid">
  <div class="panel"><h3>投递漏斗</h3><div id="funnel"></div></div>
  <div class="panel"><h3>面试归因分布 <span class="sub">挂在哪类问题</span></h3><div id="causes"></div></div>
</div>
<div class="panel" id="urgent-panel" style="display:none"><h3>临期提醒（7 天内截止且已投递）</h3><div id="urgent"></div></div>
<div class="panel" id="warn-panel" style="display:none"><h3>体检告警 <span class="sub">不阻断，但值得处理</span></h3><div id="warns"></div></div>
<style>@media(max-width:900px){.idx-grid{grid-template-columns:1fr!important}}</style>
"""

INDEX_SCRIPT = """
const D = %DATA%;
document.getElementById("stat-cards").innerHTML = D.stats.map(s=>
  `<div class="card"><div class="num ${s.c||""}">${s.v}</div><div class="lbl">${s.k}</div></div>`).join("");
const FM = [["applied","#35c98e"],["assessment","#a56ae8"],["written_test","#4da3ff"],
            ["interview_1","#ffc857"],["interview_2","#e08a4d"],["interview_more","#e06e4d"],["offer","#ff6b6b"]];
const mx = Math.max(1,...D.funnel.map(f=>f.n));
document.getElementById("funnel").innerHTML = D.funnel.map(f=>
  `<div class="dist-row"><span class="k">${f.label}</span><span class="dbar"><i style="width:${Math.max(2,f.n/mx*100)}%;background:${(FM.find(x=>x[0]===f.key)||["","#888"])[1]}"></i></span><span class="n">${f.n}</span></div>`).join("");
const CM = {"信息差":"#4da3ff","能力差":"#ff6b6b","表达差":"#ffc857","策略差":"#a56ae8"};
const cmx = Math.max(1,...D.causes.map(c=>c.n));
document.getElementById("causes").innerHTML = D.causes.length ? D.causes.map(c=>
  `<div class="dist-row"><span class="k">${c.k}</span><span class="dbar"><i style="width:${c.n/cmx*100}%;background:${CM[c.k]||"#888"}"></i></span><span class="n">${c.n}</span></div>`).join("")
  : `<div class="empty">暂无面试记录</div>`;
if(D.urgent.length){document.getElementById("urgent-panel").style.display="block";
  document.getElementById("urgent").innerHTML = D.urgent.map(u=>
    `<div class="warn-box">「${esc(u.name)} · ${esc(u.position)}」网申 ${esc(u.deadline)} 截止 · 当前 ${esc(u.stage_label)}</div>`).join("");}
if(D.warns.length){document.getElementById("warn-panel").style.display="block";
  document.getElementById("warns").innerHTML = D.warns.map(w=>`<div class="warn-box">${esc(w)}</div>`).join("");}
"""

RANK_CONTENT = """
<div class="cards" id="rank-cards"></div>
<div class="toolbar">
  <span class="sub">分数阈值</span>
  <select id="r-min"><option value="0">全部</option><option value="80">≥80</option><option value="65">≥65</option><option value="50">≥50</option></select>
  <span class="sub">条数</span>
  <select id="r-n"><option value="50">50</option><option value="30">30</option><option value="100">100</option><option value="0" selected>全部</option></select>
  <span class="sub" id="r-hint"></span>
</div>
<div class="panel">
  <h3>候选榜 <span class="sub">· 每企业取最高分公司行 · 点击展开全部在投岗位 · C红线不显示</span></h3>
  <div class="wlegend" id="wlegend"></div>
  <div class="table-wrap"><table>
    <thead><tr><th style="width:38px">#</th><th>企业</th><th>岗位</th><th>城市</th><th>分数</th><th>截止</th><th>W 各项强度</th></tr></thead>
    <tbody id="rank-body"></tbody>
  </table></div>
</div>
"""

RANK_SCRIPT = """
const D = %DATA%;
document.getElementById("wlegend").innerHTML = W_LBL.map((n,i)=>`<span><b>${n}</b> <span class="s">${W_W[i]}%</span></span>`).join("")
  + `<span style="margin-left:auto">总分 = Σ(权重×分值)/10</span>`;
function render(){
  const min=+document.getElementById("r-min").value, n=+document.getElementById("r-n").value;
  let list=D.companies.filter(c=>!c.best.scored||c.best.total>=min);
  if(n>0)list=list.slice(0,n);
  document.getElementById("r-hint").textContent=`共 ${list.length} 家候选企业 · C红线 ${D.excluded} 个 · 推进中企业 ${D.in_pipe} 家已移出`;
  const bc=document.getElementById("rank-cards");
  const top=list[0]||{best:{}};
  bc.innerHTML=[
    {n:list.length,l:"候选企业"},
    {n:D.in_pipe,l:"推进中（已移出）",c:"yellow"},
    {n:(top.best&&top.best.total)||"-",l:"最高候选 / "+((top.best&&top.best.name)||"-"),c:"green"},
    {n:D.unscored,l:"待评分岗位",c:"yellow"},
  ].map(c=>`<div class="card"><div class="num ${c.c||""}">${c.n}</div><div class="lbl">${c.l}</div></div>`).join("");
  document.getElementById("rank-body").innerHTML=list.length?list.map((c,i)=>{
    const r=i+1, cls=r===1?"r1":(r===3?"r3":"");
    const j=c.best;
    return `<tr class="expandable" onclick="toggleCo(this,'${c.key}')">
      <td class="rank ${cls}"><span class="caret">▶</span> ${r}</td>
      <td>${esc(j.name)} <span class="sub">${esc(j.track||"")}</span></td>
      <td>${esc(j.position)} ${freshBadge(j.job_posted)}</td>
      <td>${esc(j.city||"-")}</td>
      <td>${scoreCell(j)}</td>
      <td>${dlCell(j.deadline)}</td>
      <td>${wBars(j)}</td></tr>`;
  }).join(""):`<tr><td colspan="7" class="empty">无候选岗位</td></tr>`;
}
function toggleCo(tr,key){
  tr.classList.toggle("open");
  const nx=tr.nextElementSibling;
  if(nx&&nx.classList.contains("subrow")){nx.remove();return;}
  const co=D.companies.find(c=>c.key===key);
  const inner=co.jobs.map(j=>`<div class="pipe-item"><b>${esc(j.position)}</b> ${tierPill(j)} ${freshBadge(j.job_posted)}
    <span class="sub">${esc(j.city||"")}${j.salary_range?" · "+esc(j.salary_range):""}${j.deadline?" · 截止 "+esc(j.deadline):""}</span>
    <span style="float:right">${scoreCell(j)} ${wBars(j)}</span></div>`).join("");
  tr.insertAdjacentHTML("afterend",`<tr class="subrow"><td colspan="7">${inner}</td></tr>`);
}
document.getElementById("r-min").addEventListener("change",render);
document.getElementById("r-n").addEventListener("change",render);
render();
"""

PIPELINE_CONTENT = """
<div class="cards" id="pipe-cards"></div>
<div id="pipe-body"></div>
"""

PIPELINE_SCRIPT = """
const D = %DATA%;
const total=D.stages.reduce((a,s)=>a+s.items.length,0);
document.getElementById("pipe-cards").innerHTML=[
  {n:total,l:"推进中岗位",c:"yellow"},
  {n:(D.stages.find(s=>s.key==="offer")||{items:[]}).items.length,l:"已Offer",c:"red"},
  {n:D.stagnant,l:"停滞超10天",c:""},
].map(c=>`<div class="card"><div class="num ${c.c||""}">${c.n}</div><div class="lbl">${c.l}</div></div>`).join("");
document.getElementById("pipe-body").innerHTML=D.stages.map(s=>
  `<div class="pipe-stage ${s.items.length?"":"empty-stage"}">
    <h3><span class="pill ${s.pill}">${s.label}</span> <span class="tag">${s.items.length}</span></h3>
    <div class="cnt">${s.items.length?s.items.length+" 个岗位":"暂无"}</div>
    ${s.items.map(j=>jobLine(j,progBadge(j.last_node_date))).join("")||'<div class="note">—</div>'}
  </div>`).join("");
"""

ENDED_CONTENT = """
<div class="cards" id="ended-cards"></div>
<div id="ended-body"></div>
"""

ENDED_SCRIPT = """
const D = %DATA%;
document.getElementById("ended-cards").innerHTML=[
  {n:D.groups.reduce((a,g)=>a+g.items.length,0),l:"已结束"},
  ...D.groups.map(g=>({n:g.items.length,l:g.label,c:g.key==="rejected"?"red":""}))
].map(c=>`<div class="card"><div class="num ${c.c||""}">${c.n}</div><div class="lbl">${c.l}</div></div>`).join("");
document.getElementById("ended-body").innerHTML=D.groups.map(g=>
  `<div class="pipe-stage ${g.items.length?"":"empty-stage"}">
    <h3>${g.label} <span class="tag">${g.items.length}</span></h3>
    ${g.items.map(j=>jobLine(j,j.outcome_note?`<span class="sub">(${esc(j.outcome_note)})</span>`:"")).join("")||'<div class="note">—</div>'}
  </div>`).join("");
"""


# ================= 主流程 =================

def job_json(r):
    return {"id": r["id"], "name": r["name"], "position": r["position"], "city": r["city"],
            "track": r["track"], "group": r["group"], "link": r["link"],
            "salary_range": r["salary_range"], "job_posted": r["job_posted"],
            "deadline": r["deadline"], "scored": r["scored"], "total": r["score_total"] or 0,
            "tier": r["tier"] or "", "subs": r["sublist"], "note": r["note"],
            "updated_at": r["updated_at"], "boundary": r["boundary"]}


def main():
    cfg = load_config()
    files = sorted(glob.glob(str(ROOT / "data/companies/*.yml")))
    if not files:
        fail("data/companies/ 下没有数据文件")
    recs = []
    for f in files:
        rec = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        recs.append(validate_and_build(rec, cfg, Path(f).name))

    applied = [r for r in recs if r["stage_key"] != "pending"]
    pipelined = [r for r in applied if not r["outcome"]]
    ended = [r for r in recs if r["outcome"]]
    unscored_n = sum(1 for r in recs if not r["scored"])

    # ---- 体检告警 ----
    warns = []
    for r in recs:
        if r["boundary"] == "C" and r["stage_key"] != "pending":
            warns.append(f"{r['name']}·{r['position']}: C红线但已投递")
        if not r["scored"] and r["stage_key"] == "pending":
            warns.append(f"{r['name']}·{r['position']}: 待投递未评分")
        _dl = parse_date(r["deadline"]) if r["deadline"] else None
        if _dl and not r["outcome"] and r["stage_key"] == "pending" and _dl < TODAY:
            warns.append(f"{r['name']}·{r['position']}: 截止已过仍是待投递")
        _jp = parse_date(r["job_posted"]) if r["job_posted"] else None
        if _jp and _jp < datetime.date(TODAY.year, 7, 1) and not r["outcome"]:
            warns.append(f"{r['name']}·{r['position']}: 往季遗留记录 job_posted={r['job_posted']}，今年是否开放待核实")
    for w_ in warns:
        print(f"[warn] {w_}", file=sys.stderr)
    if warns:
        print(f"[warn] 体检 {len(warns)} 条告警（不阻断部署）", file=sys.stderr)

    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    today = TODAY.isoformat()
    mode = cfg["score_mode"]

    # ---- index ----
    stats = [
        {"k": "岗位总数", "v": len(recs)},
        {"k": "待投递", "v": len(recs) - len(applied)},
        {"k": "推进中", "v": len(pipelined), "c": "yellow"},
        {"k": "已Offer", "v": sum(1 for r in recs if r["stage_key"] == "offer"), "c": "red"},
        {"k": "已挂", "v": sum(1 for r in recs if r["outcome"] == "rejected")},
        {"k": "未评分", "v": unscored_n},
        {"k": "A档在投", "v": sum(1 for r in pipelined if r["tier"] == "A"), "c": "green"},
    ]
    funnel = [{"key": s["key"], "label": s["label"],
               "n": sum(1 for r in recs if s["key"] in r["reached"])} for s in cfg["stages"]]
    causes_map = defaultdict(int)
    for r in recs:
        for iv in r["interviews"]:
            if iv.get("cause"):
                causes_map[iv["cause"]] += 1
    data = {"stats": stats, "funnel": funnel,
            "causes": [{"k": k, "n": v} for k, v in sorted(causes_map.items(), key=lambda kv: -kv[1])],
            "urgent": [{"name": r["name"], "position": r["position"],
                        "deadline": r["deadline"], "stage_label": r["stage_label"]}
                       for r in recs if r["urgent"]],
            "warns": warns}
    content = INDEX_CONTENT
    script = INDEX_SCRIPT.replace("%DATA%", json_dumps(data))
    (out / "index.html").write_text(page("index", "总览", content, script, cfg, today, mode),
                                    encoding="utf-8")

    # ---- rank（候选榜：每企取最高分公司行；C红线和待定剔除）----
    # 老版规则：有推进岗位（已投递且未终结）的企业整企移出候选榜
    active_cos = {r["name"] for r in applied if not r["outcome"]}
    pend = [r for r in recs if r["stage_key"] == "pending" and not r["outcome"]
            and r["boundary"] in ("S", "A", "B") and r["name"] not in active_cos]
    excluded = sum(1 for r in recs if r["stage_key"] == "pending"
                   and r["boundary"] not in ("S", "A", "B"))
    in_pipe = len({r["name"] for r in applied if not r["outcome"]})
    by_co = defaultdict(list)
    for r in pend:
        by_co[r["name"]].append(r)
    companies = []
    for co, jobs in by_co.items():
        jobs = sorted(jobs, key=lambda r: ((0 if r["scored"] else 1), -(r["score_total"] or 0)))
        companies.append({"key": co, "best": job_json(jobs[0]),
                          "jobs": [job_json(j) for j in jobs]})
    companies.sort(key=lambda c: ((0 if c["best"]["scored"] else 1), -c["best"]["total"]))
    data = {"companies": companies, "excluded": excluded, "in_pipe": in_pipe,
            "unscored": sum(1 for c in companies for j in [c["best"]] if not j["scored"])}
    script = RANK_SCRIPT.replace("%DATA%", json_dumps(data))
    (out / "rank.html").write_text(page("rank", "候选榜", RANK_CONTENT, script, cfg, today, mode),
                                   encoding="utf-8")

    # ---- pipeline ----
    stages_data = []
    for s in cfg["stages"]:
        items = [r for r in pipelined if r["stage_key"] == s["key"]]
        stages_data.append({"key": s["key"], "label": "已" + s["label"],
                            "pill": STAGE_PILL[s["key"]],
                            "items": [{**job_json(r), "last_node_date": r["last_node_date"]}
                                      for r in items]})
    stagnant = sum(1 for r in pipelined
                   if r["last_node_date"]
                   and (TODAY - parse_date(r["last_node_date"])).days > 10)
    data = {"stages": stages_data, "stagnant": stagnant}
    script = PIPELINE_SCRIPT.replace("%DATA%", json_dumps(data))
    (out / "pipeline.html").write_text(page("pipeline", "推进中", PIPELINE_CONTENT, script,
                                            cfg, today, mode), encoding="utf-8")

    # ---- ended ----
    groups = []
    for o in cfg["outcomes"]:
        items = [r for r in ended if r["outcome"] == o["key"]]
        groups.append({"key": o["key"], "label": o["label"],
                       "items": [{**job_json(r), "outcome_note": r["outcome_note"]} for r in items]})
    data = {"groups": groups}
    script = ENDED_SCRIPT.replace("%DATA%", json_dumps(data))
    (out / "ended.html").write_text(page("ended", "已结束", ENDED_CONTENT, script,
                                         cfg, today, mode), encoding="utf-8")

    print(f"[OK] {len(recs)} 条记录 -> dist/ (index/rank/pipeline/ended)")


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    main()
