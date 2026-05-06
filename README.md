# newQuant

前后端分离的量化交易工作流项目，核心流程是观察池、监控提醒、交易计划、执行记录和复盘。

## 项目结构

- `frontend/`: React + TypeScript + Vite + Ant Design
- `backend/`: FastAPI + SQLAlchemy + SQLite
- `docs/`: 产品、技术和实施文档

## 环境要求

- Node.js 20+
- npm 10+
- Python 3.11+

后端测试和类型标注已经按 Python 3.11 口径整理；如果继续使用 3.9，本地可能会遇到语法或依赖兼容问题。

## 快速启动

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm install
npm run dev
```

前端默认访问 `http://localhost:5173`，后端默认访问 `http://localhost:8000`。

## 常用命令

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm run lint
npm run build
```

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
./venv/bin/pytest -q
./venv/bin/pytest -q --run-integration
python scripts/init_db.py
python scripts/run_scheduler.py
```

默认测试只收集 `backend/tests/test_*.py`。带外部网络依赖的测试会被标记为 `integration`，只有显式传入 `--run-integration` 才会执行。

## 配置说明

后端配置请参考 [backend/.env.example](/Users/lijiajun/ai-coding/newQuant/backend/.env.example)。

- `DATA_PROVIDER`: `tencent`、`baostock`、`akshare`、`tushare` 或 `composite`
- `TUSHARE_TOKEN`: 使用 Tushare 时必填
- `TUSHARE_API_URL`: 代理或镜像地址，可选
- `DATABASE_URL`: 数据库连接串
- `DATA_DIR`: SQLite 数据文件目录
- `AUTO_INIT_DB`: 是否在 FastAPI 启动时初始化数据库
- `RUN_STARTUP_MIGRATIONS`: 是否在初始化数据库时执行脚本迁移
- `AUTO_START_SCHEDULER`: 是否在 Web 进程内自动启动调度器
- `SCHEDULER_ENABLED`: 是否允许调度器运行
- `CORS_ORIGINS`: 允许访问后端的前端地址白名单
- `AI_PROVIDER`: `openai`、`qwen` 或 `ollama`

推荐的生产/长期运行方式是把 Web 服务和调度器拆开：

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
source venv/bin/activate
python scripts/init_db.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
source venv/bin/activate
python scripts/run_scheduler.py
```

如果仍想保持原来的单进程行为，可以在 `.env` 中设置 `AUTO_START_SCHEDULER=true`。

更多业务背景和设计说明见 [docs/README.md](/Users/lijiajun/ai-coding/newQuant/docs/README.md)。
