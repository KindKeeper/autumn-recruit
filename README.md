# 秋招投递记录

结构化的秋招投递追踪 + 自动生成看板页面，数据即 YAML 文件，git 即备份。

- 在线看板：https://kindkeeper.github.io/autumn-recruit/
- 数据目录：`data/companies/*.yml`，一司一文件
- 全局配置：`config.yml`（节点枚举、评分权重、分档阈值）

## 流程模型

七节点：`applied(投递) → assessment(测评) → written_test(笔试) → interview_1(一面) → interview_2(二面) → interview_more(更多面) → offer`

八阶段由脚本推导：无 `applied` 为**待投递**，否则为"已" + 当前最高节点名。
`outcome`（rejected/pool/signed）是正交终态标签，不参与阶段推导。

## 评分与优先级

八子项 0-10 打分（jobhunt v3.0 口径，合计 100）：

| 子项 | 权重 | 锚点要点 |
|---|---|---|
| fit 匹配 | 25 | 技术栈+方向对口程度 |
| track 赛道 | 15 | 企业赛道与主线契合度 |
| city 城市 | 20 | 按个人 20 城排序（合肥主场优先） |
| salary 薪资 | 10 | 总包与时薪综合 |
| stability 稳定 | 10 | 业务线/公司收缩风险 |
| certainty 确定 | 10 | offer 确定性（流程透明/养鱼名声） |
| urgency 紧迫 | 5 | 按投递截止剩余天数 |
| wlb 强度 | 5 | 加班文化 |

总分 = Σ(子项 × 权重) / 10。档位：≥80 A必投 / ≥65 B重点投 / ≥50 C顺手投 / 其余 D观望。
`boundary: C` 为红线岗位，不进优先级总表。未评分的记录显示"未评分"排最后。

## 数据来源

- 2026-09-08 由 `tools/migrate.py` 从本机 jobhunt.db 全量迁移（160 岗位 / 113 家企业）
- `job_posted` 由 offershow 校招信息表回填（命中 110/113，核对明细见本地 outputs/verification_report.md，不入库）
- offershow 原始响应只缓存于 /tmp，不进仓库；会员 cookie 等凭证严禁入库

## 隐私红线（public 仓库）

- 禁止录入：手机号、身份证号、住址、成绩单、薪资证明、面试官真名、内推人可定位信息
- 内推人只记昵称；`note`/`log` 只写题目方向与体感
- 录入入口（脚本/Issue 自动化）内置正则预检，命中即拒绝提交

## 字段速查

每个公司文件：`id / name / position / group / channel / city / link / referrer / salary_range / job_posted / apply_deadline / stages / outcome / score / log / tags / note / updated_at`

- 日期一律 `"YYYY-MM-DD"` 带引号字符串
- `stages` 的 key 只能取七节点枚举值；值可以是日期字符串或 `{date, note}` 对象
- 单调性：interview_2 ⇒ interview_1 必先存在；offer ⇒ 至少 interview_1
- 当前阶段与优先级档位由 build 脚本自动推导，**不要手填**
