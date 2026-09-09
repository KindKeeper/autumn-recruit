# AGENTS.md

面向 AI agent 的仓库说明。人类用户看 `docs/`，agent 先看这个文件。

## 这个仓库是什么

秋招投递追踪站：YAML 数据 → `build.py` 生成静态页 → GitHub Pages。public 仓库。

- 在线地址：https://kindkeeper.github.io/autumn-recruit/
- 架构细节：`docs/architecture.md`；字段定义：`docs/data-model.md`；人工操作：`docs/operations.md`

## 硬约束（违反即错误）

1. **隐私红线**：禁止写入手机号、身份证号、住址、成绩单、薪资证明、面试官真名、内推人可定位信息。用户邮件/截图里的个人信息绝不入库。build.py 有正则门禁，命中即失败，不允许绕过。
2. **凭证不入库**：offershow cookie 等凭证只存本地并 gitignore；offershow 原始 API 响应只缓存 /tmp，严禁入库。
3. **不手填推导字段**：当前阶段、评分总分、档位由 build.py 计算，不落盘。
4. **进度更新必须先确认岗位**：同一公司多岗位时，一封流程邮件（测评/笔试/面试）绝不能推断到全部岗位。单一岗位可直接记录；多岗位先标记"待确认"或问用户岗位名，再落库。
5. **七节点命名固定**：applied / assessment / written_test / interview_1 / interview_2 / interview_more / offer，不得增删或改名。八阶段由最高已达节点推导。

## 构建命令

```bash
.venv/bin/python build.py    # 唯一入口；校验失败非零退出（CI 门禁）
```

不要用系统 pip 装包（PEP 668）。修改 `config.yml` / `build.py` / 模板后必须本地跑通再 push。

## 数据约定

- 一司一岗一文件 `data/companies/<公司-岗位>.yml`
- 日期一律 `"YYYY-MM-DD"` 带引号字符串（YAML 裸日期会被解析成 date 对象，破坏比较）
- YAML 特殊字符（`: `、`#`、`&`、中文括号一般无碍，但值含冒号空格时必须引号）保守起见一律给字符串加引号
- `outcome` 正交于阶段：rejected / given_up / frozen / expired / pool / signed
- 未评分记录合法（显示"未评分"排候选榜最后），但新收录岗位应尽量评分
- 候选榜规则：有推进中岗位（已投递未终结）的企业**整企移出**候选榜

## 常见坑

- Jinja 模板里 dict 的 key 不能用 `items`（撞 dict 内置方法），页面数据用 `cards` 等命名
- `build.py` 的 warn（体检）不阻断构建；fail（校验）才退出非零
- 收录新岗位参考 `data/companies/ALI-example.yml`

## offershow 集成

无官方 API，`POST https://www.offershow.cn/api/od/plan_table`（form-urlencoded），`search_content` 参数服务端生效，`size` 上限 100，`time_type==1` 才有具体截止。工具：`tools/sync_posted.py`、`tools/sync_deadlines.py`，详见 architecture.md。
