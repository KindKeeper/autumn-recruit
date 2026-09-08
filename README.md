# 秋招投递记录

结构化的秋招投递追踪 + 自动生成看板页面，数据即 YAML 文件，git 即备份。

- 在线看板：（部署后补充 Pages 地址）
- 数据目录：`data/companies/*.yml`，一司一文件
- 全局配置：`config.yml`（节点枚举、评分权重、分档阈值）

## 流程模型

七节点：`applied(投递) → assessment(测评) → written_test(笔试) → interview_1(一面) → interview_2(二面) → interview_more(更多面) → offer`

八阶段由脚本推导：无 `applied` 为**待投递**，否则为"已" + 当前最高节点名。
`outcome`（rejected/pool/signed）是正交终态标签，不参与阶段推导。

## 评分与优先级

七子项 0-10 打分（锚点：9-10 极好 / 7-8 好 / 5-6 一般 / 3-4 差 / 0-2 很差）：

| 子项 | 权重 | 锚点要点 |
|---|---|---|
| fit 岗位匹配度 | 25 | 技术栈+方向对口程度 |
| salary 薪资福利 | 20 | 总包与时薪综合 |
| platform 公司平台 | 15 | 公司层级与行业地位 |
| business 业务前景 | 10 | 核心业务/增长性/裁员风险 |
| city 城市因素 | 10 | 落户、生活成本、长期定居意愿 |
| odds 录取概率 | 15 | 学历匹配、HC、竞争度、内推质量 |
| wlb 工作生活平衡 | 5 | 加班强度 |

总分 = Σ(子项 × 权重) / 10。档位：≥80 A必投 / ≥65 B重点投 / ≥50 C顺手投 / 其余 D观望。
`score_mode: expected` 时改用 期望优先级 = 吸引力 × odds / 10。

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
