# 数据模型

## 文件约定

`data/companies/{公司简称}-{岗位名}.yml`，一司一岗一文件。`id` 全局唯一（旧数据为 `job-NNNN`，新数据为 `{slug}-2027`）。

## 字段完整参考

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一 ID |
| `name` | string | ✅ | 公司简称 |
| `position` | string | ✅ | 岗位名 |
| `group` | enum | ✅ | 提前批/正式批/实习/未启动/补录 |
| `channel` | enum | ✅ | 官网/邮箱/内推/智联/BOSS直聘/牛客/宣讲会/猎聘/其他 |
| `city` | string | ⬜ | 工作城市 |
| `link` | url | ⬜ | 投递/JD 链接 |
| `salary_range` | string | ⬜ | 必须加引号（含 `·`、`-` 等特殊字符） |
| `job_posted` | date | ⬜ | 岗位发布日，格式 `'YYYY-MM-DD'`。以 JD 为准，可用 offershow 回填 |
| `job_code` | string | ⬜ | 官网岗位编号（如 J45454） |
| `apply_deadline` | date | ⬜ | 网申截止。非日期文本（"尽快投递"）也允许 |
| `stages` | map | ✅ | 七节点时间（见下），值可为 `'YYYY-MM-DD'` 或 `{date, note}` |
| `outcome` | enum | ⬜ | rejected/given_up/frozen/expired/pool/signed（正交于节点） |
| `outcome_note` | string | ⬜ | 挂因等 |
| `boundary` | enum | ⬜ | 专业边界 S/A/B/C/待定，C=红线剔除出候选榜 |
| `track` | string | ⬜ | 岗位分类（热管理类/仿真类/…） |
| `score` | map | ⬜ | 八子项 0-10 整数（见下）；缺省=未评分，看板置底 |
| `score_rationale` | string | ⬜ | 评分依据，权重调整后复核用 |
| `interviews` | list | ⬜ | `{round, date, stuck, cause, result}`，cause ∈ 信息差/能力差/表达差/策略差 |
| `log` | list | ⬜ | `{date, note}` 流水，note 建议带 `[来源]` 前缀：官网/邮箱/offershow |
| `tags` | list | ⬜ | 企业分类等 |
| `note` | string | ⬜ | 备注 |
| `updated_at` | date | ✅ | 最后更新，构建不自动写，手动维护 |
| `source_id` | string | ⬜ | 来源溯源（如 `offershow:{uuid}`） |
| `referral_code` | string | ⬜ | 内推码 |

## 七节点与八阶段

节点（`stages` 的 key，顺序即漏斗）：`applied(投递) → assessment(测评) → written_test(笔试) → interview_1(一面) → interview_2(二面) → interview_more(更多面) → offer`

阶段由脚本推导，**不手填**：无 `applied` = 待投递；否则 = "已" + 最高已达节点。节点允许跳空（无测评直接笔试合法）；单调性约束：interview_2⇒interview_1、offer⇒interview_1。`outcome` 是终态标签，有 rejected 后不应再新增节点。

## 评分体系（jobhunt v3.0 口径）

总分 = Σ(子项 × 权重) / 10，档位 ≥80 A / ≥65 B / ≥50 C / 其余 D。

| 子项 | 权重 | 锚点 |
|---|---|---|
| fit 匹配 | 25 | 9-10 完全对口 / 7-8 核心栈匹配 / 5-6 沾边 / ≤4 转行 |
| track 赛道 | 15 | 企业赛道与主线契合度 |
| city 城市 | 20 | 按个人 20 城排序（合肥 10 第一档） |
| salary 薪资 | 10 | 总包与时薪综合 |
| stability 稳定 | 10 | 业务线/收缩风险 |
| certainty 确定 | 10 | offer 确定性（流程透明/养鱼名声） |
| urgency 紧迫 | 5 | 按截止剩余天数 |
| wlb 强度 | 5 | 加班文化 |

权重集中在 `config.yml`，调整权重无需改数据（`score_rationale` 供复核）。

## 隐私红线（public 仓库）

禁录：手机号、身份证号、住址、成绩单、薪资证明、面试官真名、内推人可定位信息。build.py 内置正则预检，命中即构建失败——这是 CI 门禁，不是提醒。
