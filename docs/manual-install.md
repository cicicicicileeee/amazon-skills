# Manual Install

当你的 IDE 暂时不能一步完成“自然语言安装”时，再使用这份手动安装说明。

## 1. 克隆仓库

```bash
git clone https://github.com/cicicicicileeee/amazon-skills.git
cd amazon-skills
```

## 2. 选择目标 skill

当前示例：

- [`skills/cici-amazon-brand-research`](../skills/cici-amazon-brand-research/README.md)（v1.0.0）
- `skills/zach-feature-demand-validator`
- `skills/zach-listing-health-checker`

## 3. 放到你的工作区

### Claude Code / Claude App

把目标 skill 目录复制到你的工作区：

```bash
mkdir -p /path/to/your-workspace/.claude/skills
cp -R skills/zach-feature-demand-validator /path/to/your-workspace/.claude/skills/
```

或：

```bash
cp -R skills/zach-listing-health-checker /path/to/your-workspace/.claude/skills/
```

安装品牌调研 Skill（保留整个目录及其支持文件）：

```bash
cp -R skills/cici-amazon-brand-research /path/to/your-workspace/.claude/skills/
```

### Codex / Cursor

优先还是让 AI 读取仓库中的 skill 并帮你完成安装。  
如果你必须手动处理，请把目标 skill 目录复制到你自己的工作区技能目录，或按你当前 IDE 的本地 skill/import 机制指向该目录。

## 4. 验证

安装完成后，对 AI 说：

```text
请使用 zach-feature-demand-validator，帮我验证 air fryer 加 steam 功能在美国站是不是真需求。
```

品牌调研 Skill 安装完成后，对 AI 说：

```text
使用 $cici-amazon-brand-research 调研 Anker 在 Amazon.de 的经营表现。
```
