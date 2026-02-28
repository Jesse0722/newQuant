# 使用 Superpowers 进行问答式规划

本项目推荐使用 [Superpowers](https://github.com/obra/superpowers) 的 **brainstorming** skill，以问答形式进行产品设计与规划，避免直接写代码。

---

## 安装 Superpowers（Cursor）

在 **Cursor Agent 聊天** 中输入：

```
/plugin-add superpowers
```

安装后，Agent 会在创意工作前自动触发 brainstorming skill。

---

## Brainstorming 工作流（问答式规划）

1. **探索项目上下文** — 检查文件、文档、最近提交
2. **逐条提问澄清** — 一次一个问题，理解目的/约束/成功标准
3. **提出 2–3 种方案** — 含利弊与推荐
4. **分节呈现设计** — 按复杂度分块，每节后征求确认
5. **撰写设计文档** — 保存到 `docs/plans/YYYY-MM-DD-xxx-design.md`
6. **转入实施** — 调用 writing-plans 生成实施计划

**原则**：一次只问一个问题；优先用选择题；设计获批前不写代码。

---

## 在本项目中的用法

- **规划新功能**：直接说「帮我规划 xxx 功能」或「let's brainstorm xxx」，Agent 会按上述流程提问
- **继续脑暴**：参考 `docs/02-脑暴续-待定稿.md` 中的待拍板项，逐项用问答形式定稿
- **设计文档**：定稿后保存到 `docs/plans/`，与 `01-产品设计-定稿.md` 保持一致

---

## 手动触发（若未安装插件）

若未安装 Superpowers，可在对话中明确要求：

> 请用问答形式进行规划：一次只问一个问题，等我回答后再继续；先完成设计并得到我确认，再写实施计划或代码。

或直接引用本文件：

> 参考 docs/PLANNING_WITH_SUPERPOWERS.md，用 brainstorming 流程来规划。
