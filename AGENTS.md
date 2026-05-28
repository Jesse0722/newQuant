# AGENTS.md

This file defines the long-term multi-agent collaboration model for the `newQuant` repository.

It applies to the whole project, not only to one feature or one initiative.

## 1. Project Identity

`newQuant` is a quantitative research workflow app. Its main workflow is:

```text
观察池 -> 买点雷达 -> 买点提醒 -> 交易计划 -> 执行记录 -> 复盘
```

The product is a research and decision-support system. It must not become an automatic trading system, and it must not present model output as guaranteed investment advice.

Core principles:

- Evidence first.
- Small reversible changes.
- Preserve existing user workflows.
- Keep research conclusions traceable.
- Do not overwrite unrelated user or agent work.

## 2. Multi-Agent Operating Model

The project uses a supervised multi-agent model.

There is one supervising agent and one or more implementation agents.

### 2.1 Supervisor

The supervisor is responsible for:

- Turning user intent into scoped tasks.
- Assigning tasks to implementation agents.
- Keeping work aligned with product direction and technical design.
- Reviewing outputs before follow-up work starts.
- Preventing duplicate, conflicting, or oversized changes.
- Checking that tests and migration notes are adequate.
- Maintaining this `AGENTS.md` when collaboration rules evolve.

The supervisor should not approve work only because it compiles. Review should also consider product fit, evidence quality, migration safety, and user workflow impact.

### 2.2 Implementation Agents

Implementation agents are responsible for:

- Reading the required context before changing files.
- Taking one scoped task at a time.
- Making the smallest coherent change that solves the task.
- Reporting exactly what changed and how it was verified.
- Calling out blockers, assumptions, and residual risks.

Implementation agents should not silently expand scope. If a task reveals a larger architectural issue, report it and wait for supervisor direction unless the fix is clearly required and tightly bounded.

### 2.3 Reviewer Agents

A reviewer agent may be asked to inspect a change. It should use a code-review stance:

- Findings first.
- Prioritize bugs, regressions, migration risk, data loss, security issues, and missing tests.
- Include file and line references.
- Keep summaries secondary.

Reviewer agents should not rewrite the implementation unless explicitly asked.

## 3. Task Lifecycle

Every meaningful task should move through this lifecycle:

```text
Brief -> Context Read -> Plan -> Implement -> Verify -> Report -> Review -> Next Task
```

### 3.1 Brief

The task brief should include:

- Objective.
- Files or modules likely involved.
- Non-goals.
- Acceptance criteria.
- Required tests or checks.
- Known risks.

### 3.2 Context Read

Before editing, agents must inspect:

- Relevant docs.
- Existing models, schemas, services, routers, and frontend APIs.
- Current git status.
- Nearby tests.

Agents should prefer `rg` and `rg --files` for code search.

### 3.3 Plan

For non-trivial tasks, agents should state a short plan before editing. The plan should be concrete enough for review, but not so detailed that it becomes ceremony.

### 3.4 Implement

Implementation should follow existing code patterns and keep edits scoped.

### 3.5 Verify

Agents must run relevant tests or checks when feasible. If not feasible, they must explain why.

### 3.6 Report

The final task report should include:

- What changed.
- Files changed.
- Tests/checks run.
- What was not tested.
- Risks or follow-up work.

Database and migration tasks must also include backup, migration, and rollback notes.

## 4. Repository Guardrails

This repository may contain uncommitted user changes or work from other agents.

Before editing, run:

```bash
git status --short
```

Agents must not revert, overwrite, or reformat unrelated changes.

If a file has unrelated edits, read it carefully and make the smallest compatible change.

Never run destructive commands such as:

```bash
git reset --hard
git checkout -- .
git clean -fd
```

unless the user explicitly asks for that operation.

Do not make broad formatting-only changes unless the task is explicitly about formatting.

## 5. Required Project Context

Every agent should understand the repository layout:

```text
backend/   FastAPI + SQLAlchemy + Pydantic
frontend/  React + TypeScript + Vite + Ant Design
docs/      Product, design, and implementation plans
```

Start with:

- `README.md`
- `docs/README.md` if the task touches product direction or architecture.
- `docs/development-postgresql.md` if the task touches database configuration, migrations, Docker, or local environment setup.

Then read task-specific documents.

For message center and industry research tasks:

- `docs/plans/舆情分析模块需求.md`
- `docs/plans/2026-05-14-message-opportunity-technical-design.md`
- `backend/app/models/message.py`
- `backend/app/schemas/message.py`
- `backend/app/services/message_service.py`
- `backend/app/routers/messages.py`
- `frontend/src/pages/Messages/MessageCenterPage.tsx`

For stock AI analysis tasks:

- `docs/plans/2026-05-19-stock-ai-analysis-design.md`
- `backend/app/services/ai_analysis_service.py`
- `backend/app/services/llm_client.py`
- `backend/app/models/stock.py`

For strategy, pool, and trading workflow tasks:

- Relevant files under `backend/app/services/`
- Relevant files under `backend/app/routers/`
- Relevant files under `frontend/src/pages/`
- Existing tests under `backend/tests/` and `frontend/tests/`

For the current industry GraphRAG report initiative:

- `docs/plans/2026-05-28-industry-graphrag-report-technical-design.md`
- `docs/plans/2026-05-28-industry-graphrag-report-tasks.md`
- `docs/development-postgresql.md`

## 6. Technical Baseline

Backend:

- Python 3.11+
- FastAPI
- SQLAlchemy
- Pydantic v2
- Current MVP database: SQLite
- Target long-term database: PostgreSQL
- LLM abstraction: `backend/app/services/llm_client.py`

Frontend:

- React
- TypeScript
- Vite
- Ant Design

Common commands:

```bash
cd backend
./venv/bin/pytest -q
```

```bash
cd frontend
npm run lint
npm run build
```

Use more specific tests when available.

## 7. Role Patterns

The supervisor may assign work using these role patterns.

### 7.1 Backend Agent

Typical responsibilities:

- SQLAlchemy models.
- Pydantic schemas.
- FastAPI routers.
- Service logic.
- Data migration scripts.
- Backend tests.

Quality bar:

- Preserve API compatibility unless the task requires a change.
- Keep business rules in services, not in routers.
- Add tests for scoring, parsing, migrations, and edge cases.

### 7.2 Frontend Agent

Typical responsibilities:

- Pages and components.
- API client functions.
- TypeScript types.
- Loading, empty, and error states.
- Frontend tests.

Quality bar:

- Operational UI, not marketing UI.
- Dense, scannable, responsive layouts.
- No text overlap.
- Clear user actions and feedback.

### 7.3 Data/Migration Agent

Typical responsibilities:

- Database configuration.
- Alembic migrations.
- Data migration scripts.
- Backups and rollback notes.
- Count and integrity validation.

Quality bar:

- No data loss.
- Idempotent or clearly documented migration behavior.
- Validation output for important tables.

### 7.4 AI/LLM Agent

Typical responsibilities:

- Prompt design.
- Structured output parsing.
- LLM error handling.
- Model-provider integration.
- Mocked tests.

Quality bar:

- Strict JSON where structured output is required.
- Fail gracefully on parsing errors.
- Keep scoring and trading decisions outside the model when possible.
- Make evidence and uncertainty explicit.

### 7.5 QA/Reviewer Agent

Typical responsibilities:

- Review diffs.
- Run targeted tests.
- Check regressions.
- Verify migration and UI behavior.

Quality bar:

- Findings first.
- Concrete reproduction steps.
- Clear severity and file references.

## 8. Engineering Standards

Follow existing local patterns before inventing new abstractions.

Prefer:

- Small services over large monolith functions.
- Typed schemas for API boundaries.
- Structured parsing over ad hoc string manipulation.
- Tests close to the changed behavior.
- Backward-compatible API changes.

Avoid:

- Large unrelated refactors.
- Silent behavior changes.
- Global formatting churn.
- Duplicating business rules between frontend and backend.
- Making LLM output the only source of truth for critical decisions.

## 9. Database Standards

Database changes must include:

- ORM model changes.
- Migration files when Alembic is active for the target area.
- Indexes for common query paths.
- Data migration scripts when existing data is affected.
- Tests or validation steps.

For major migrations, include:

- Backup step.
- Dry-run or validation mode if practical.
- Row-count checks.
- Rollback notes.

The long-term direction is PostgreSQL as the main database for all business data. Do not create a split-brain design where new modules use PostgreSQL while core K-line and workflow data remain actively maintained in SQLite.

## 10. AI and Investment Safety

The system is for research support only.

Agents must not add UI text, prompts, reports, or API responses that imply:

- Guaranteed profit.
- Certain price movement.
- Automatic buy/sell decisions.
- Replacement for human judgment.

Preferred wording:

- "候选"
- "观察"
- "证据不足"
- "待验证"
- "风险观察"
- "加入观察池等待买点雷达确认"

Avoid wording:

- "必涨"
- "稳赚"
- "确定买入"
- "强烈推荐买入"
- "无风险"

LLM-generated conclusions must be evidence-bound. If evidence is weak, say so.

## 11. Frontend Product Standards

This app is a work tool for repeated research workflows.

Use:

- Tables.
- Filters.
- Tags.
- Compact panels.
- Clear action buttons.
- Expandable evidence/details.
- Loading, empty, and error states.

Avoid:

- Landing-page style hero sections.
- Decorative layouts that reduce scan speed.
- Large card stacks when a table is more efficient.
- Text-heavy explanations inside the app for obvious workflows.

## 12. Current Roadmap Context

The current strategic initiative is documented here:

- `docs/plans/2026-05-28-industry-graphrag-report-technical-design.md`
- `docs/plans/2026-05-28-industry-graphrag-report-tasks.md`

Current recommended order:

1. PostgreSQL 主库迁移。
2. 图谱基础模型与种子导入。
3. DeepSeek 实体/关系抽取。
4. 产业链路径与候选评分。
5. 每日产业链报告生成。
6. 前端消息中心展示。
7. 调度、测试与部署文档。

This roadmap is current context, not the whole purpose of the repository. Future initiatives should add or update roadmap documents without turning this file into a feature-specific spec.

## 13. Handoff Format

When an implementation agent completes work, report:

```text
Summary:
- ...

Files changed:
- ...

Verification:
- ...

Not tested:
- ...

Risks / follow-up:
- ...
```

For migrations:

```text
Migration notes:
- Backup:
- Command:
- Validation:
- Rollback:
```

For LLM work:

```text
LLM notes:
- Provider/model:
- Prompt version:
- Parsing behavior:
- Failure handling:
- Hallucination controls:
```

## 14. When to Ask the User

Agents should make reasonable implementation decisions when the design and local context are clear.

Ask the user or supervisor when:

- A change affects product direction.
- A migration may risk data loss.
- A dependency or service has cost/security implications.
- The task requires credentials or external accounts.
- There are conflicting requirements.

Do not ask for confirmation for routine local implementation details that are already covered by project patterns.
