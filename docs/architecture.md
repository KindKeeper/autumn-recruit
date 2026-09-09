# 技术架构

## 总体设计

```
data/companies/*.yml ──→ build.py ──→ dist/*.html ──→ GitHub Actions ──→ GitHub Pages
   (YAML 数据)          校验+推导+渲染   (静态页面)        push 自动触发      在线访问
        ↑                                                     │
   git 历史 = 备份 + 审计                                     ▼
                                          https://kindkeeper.github.io/autumn-recruit/
```

核心原则：**数据与展示彻底分离**。仓库里只有纯数据（YAML）和代码，HTML 永远由构建产出，人手不直接编辑页面。git 历史即备份，push 即发布。

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 数据存储 | 一司一岗一 YAML（`data/companies/*.yml`） | git diff 内聚、GitHub 网页端可直接编辑、零依赖 |
| 解析 | PyYAML（safe_load） | 钉版本于 CI（pip install pyyaml jinja2） |
| 构建 | Python 3 标准库 + Jinja2，单文件 `build.py` | 无 Node 生态，本地/CI 同一入口 |
| 页面 | 多页静态 HTML + 内嵌 JSON + vanilla JS | 无后端、无外部请求，数据以内嵌 `const D = {...}` 进页面，筛选交互纯前端 |
| 托管 | GitHub Pages（workflow 模式） | push 后约 1 分钟自动更新 |
| CI | GitHub Actions（`.github/workflows/deploy.yml`） | build 失败即部署失败 = 数据质量门禁 |

## 页面结构（4 页）

| 页面 | 内容 | 数据源要点 |
|---|---|---|
| `index.html` 总览 | 统计卡、七节点漏斗、面试归因分布、临期提醒、体检告警 | — |
| `rank.html` 候选榜 | 待投递排行榜：每企业取最高分公司行，点击展开全部在投岗位 | 排除：C 红线、推进中企业（整企移出）、未评分置底 |
| `pipeline.html` 推进中 | 七阶段分组，停滞徽章（按最近节点天数变色） | 推进中 = 已投递且未终结 |
| `ended.html` 已结束 | 按 outcome 分组（已挂/已放弃/已冻结/已过期/泡池子/已签约） | — |

## 构建与校验

`build.py` 两个阶段：

1. **校验（fail 即退出，阻断 CI）**：必填字段、七节点枚举、单调性（interview_2⇒interview_1、offer⇒interview_1）、outcome 枚举、日期合法性（节点 ≥ job_posted、不在未来）、score 子项 0-10、**隐私正则（手机号/身份证命中即失败）**
2. **体检（warn 不阻断）**：C 红线但已投递、待投递未评分、截止已过仍待投递

推导规则：当前阶段 = 最高已达节点（无 `applied` 即"待投递"）；评分总分与 A/B/C/D 档位构建时计算，**不落盘**。

## 工具链（`tools/`，仅本地运行，不进 CI）

| 工具 | 用途 |
|---|---|
| `migrate.py` | 一次性迁移：SQLite(jobhunt.db) → YAML，并用 offershow 回填 job_posted |
| `sync_posted.py` | 按岗位批次从 offershow 校正发布时间（批次内取最新公告；实体分级+子品牌剔除防误配） |
| `sync_deadlines.py` | 用 offershow 校验/更新 apply_deadline（只采纳未截止的具体日期） |

offershow 集成说明：调其未公开 Web API（`POST /api/od/plan_table`，`search_content` 参数），无官方 API。原始响应只缓存于 `/tmp`，**严禁入库**；会员 cookie 等凭证只存本地且必须 gitignore。

## 本地开发

```bash
python3 -m venv .venv && .venv/bin/pip install pyyaml jinja2
.venv/bin/python build.py        # 生成 dist/，校验失败非零退出
```

注意：系统 Python 是 PEP 668 托管环境，不要全局 pip install，一律用 `.venv`。
