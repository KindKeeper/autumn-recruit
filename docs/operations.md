# 日常使用手册

## 本地构建

```bash
.venv/bin/python build.py     # 生成 dist/；校验失败非零退出并打印全部错误
```

系统 Python 是 PEP 668 托管，不要全局 `pip install`，依赖只装在 `.venv`（pyyaml + jinja2）。

## 记一次进度

1. 改对应文件 `data/companies/<公司-岗位>.yml` 的 `stages`（key 只能取七节点枚举）
2. 随手更新 `updated_at`
3. 本地跑一遍 `build.py` 确认过校验
4. `git add -A && git commit -m "..." && git push`
5. Actions 约 1 分钟部署完，线上页面自动更新

节点值两种写法：`applied: "2026-09-07"` 或 `interview_1: {date: "2026-09-08", note: "线上，问散热仿真"}`。

## 收录一个新岗位

1. 复制 `data/companies/ALI-example.yml`（或任一现有文件）改名 `公司-岗位.yml`
2. 填 `id`（唯一）、`name`、`position`、`city`、`job_posted`、`link`，八子项 `score`
3. `stages` 留空 = 待投递，会进候选榜；填了 `applied` 即进入推进管道
4. 跑 `build.py` → commit → push

## 从 offershow 校对发布/截止时间

```bash
.venv/bin/python tools/sync_posted.py 公司名     # 校正 job_posted（批次内取最新）
.venv/bin/python tools/sync_deadlines.py 公司名 # 校验 apply_deadline
```

两者都会打印采纳/拒绝明细供人工确认。offershow 原始响应只缓存 `/tmp`，凭证（cookie）只放本地、必须 gitignore。

## CI 流程

push 到 `main` 触发 `.github/workflows/deploy.yml`：校验数据 → 构建 `dist/` → 部署 Pages。校验失败则整个部署失败，线上保持上一版——坏数据永远上不了线。

## 回滚

任何修改都有 git 历史。数据坏了：`git log --oneline data/companies/` 找到好版本 `git checkout <sha> -- data/companies/` 再 push。整站回滚：`git revert <sha>`。

## 常见报错

| 报错 | 原因 | 处理 |
|---|---|---|
| `stages key ... 非法` | key 不在七节点枚举 | 改回标准 key |
| `单调性` | interview_2 先于 interview_1 等 | 补上前置节点 |
| `日期在未来` / `节点早于 job_posted` | 日期笔误 | 修正日期 |
| `隐私内容命中` | 手机号/身份证样式文本 | 删掉或脱敏（红线，不允许绕过） |
| warn: C 红线但已投递 | 体检提醒 | 确认是否要撤投 |
