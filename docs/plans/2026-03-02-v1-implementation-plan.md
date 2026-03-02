# V1 实施计划

> **执行方式：** 使用 subagent-driven-dev 规则逐任务实施。

**目标：** 实现量化交易系统 V1 全部功能，包括观察池、数据同步、监控提醒、交易计划、前端页面。

**架构：** FastAPI 后端 + React 前端 + SQLite 存储，Tushare Pro 数据源，后台线程处理同步和扫描。

**技术栈：** Python/FastAPI/SQLAlchemy/Pandas（后端）、React/TypeScript/Ant Design/Vite（前端）

---

## Phase 1：基础骨架

### 任务 1.1：项目结构 + 依赖

**文件：**
- 创建：`backend/app/__init__.py`
- 创建：`backend/app/models/__init__.py`
- 创建：`backend/app/schemas/__init__.py`
- 创建：`backend/app/routers/__init__.py`
- 创建：`backend/app/services/__init__.py`
- 创建：`backend/app/tasks/__init__.py`
- 修改：`backend/requirements.txt`
- 修改：`backend/.env.example`

**步骤 1：创建目录结构**

```bash
mkdir -p backend/app/{models,schemas,routers,services,tasks}
mkdir -p backend/tests
mkdir -p backend/data
touch backend/app/__init__.py
touch backend/app/models/__init__.py
touch backend/app/schemas/__init__.py
touch backend/app/routers/__init__.py
touch backend/app/services/__init__.py
touch backend/app/tasks/__init__.py
```

**步骤 2：更新 requirements.txt**

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
tushare>=1.2.89
pandas>=2.0.0
sqlalchemy>=2.0.0
python-dotenv>=1.0.0
pydantic>=2.0.0
python-multipart>=0.0.6
```

**步骤 3：更新 .env.example**

```
TUSHARE_TOKEN=your_tushare_token_here
DATABASE_URL=sqlite:///./data/quant.db
DATA_DIR=./data
```

**步骤 4：验证**

```bash
cd backend && pip install -r requirements.txt
```

**步骤 5：提交**

```bash
git add -A && git commit -m "chore: 初始化项目目录结构和依赖"
```

---

### 任务 1.2：配置模块

**文件：**
- 创建：`backend/app/config.py`

**步骤 1：编写 config.py**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'quant.db'}")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
```

**步骤 2：验证**

```bash
python -c "from app.config import DATABASE_URL, TUSHARE_TOKEN; print(DATABASE_URL)"
```

**步骤 3：提交**

```bash
git add backend/app/config.py && git commit -m "feat: 添加配置模块"
```

---

### 任务 1.3：数据库引擎

**文件：**
- 创建：`backend/app/database.py`

**步骤 1：编写 database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    import app.models  # noqa: F401 — 确保所有模型被注册
    Base.metadata.create_all(bind=engine)
```

**步骤 2：验证**

```bash
python -c "from app.database import engine; print(engine.url)"
```

**步骤 3：提交**

```bash
git add backend/app/database.py && git commit -m "feat: 添加数据库引擎和会话管理"
```

---

### 任务 1.4：ORM 模型 — stock.py

**文件：**
- 创建：`backend/app/models/stock.py`

**步骤 1：编写 StockBasic + DailyQuote 模型**

```python
from sqlalchemy import Column, String, Float
from app.database import Base

class StockBasic(Base):
    __tablename__ = "stock_basic"
    ts_code = Column(String(16), primary_key=True)
    symbol = Column(String(10))
    name = Column(String(32), nullable=False)
    area = Column(String(16))
    industry = Column(String(32))
    market = Column(String(16))
    list_date = Column(String(8))
    list_status = Column(String(2))

class DailyQuote(Base):
    __tablename__ = "daily_quote"
    ts_code = Column(String(16), primary_key=True)
    trade_date = Column(String(8), primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    pre_close = Column(Float)
    change = Column(Float)
    pct_chg = Column(Float)
    vol = Column(Float)
    amount = Column(Float)
```

**步骤 2：提交**

```bash
git add backend/app/models/stock.py && git commit -m "feat: 添加 StockBasic 和 DailyQuote 模型"
```

---

### 任务 1.5：ORM 模型 — pool.py

**文件：**
- 创建：`backend/app/models/pool.py`

**步骤 1：编写 WatchPool + WatchStock 模型**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

def gen_uuid():
    return str(uuid.uuid4())

class WatchPool(Base):
    __tablename__ = "watch_pool"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    default_monitor_rule = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    stocks = relationship("WatchStock", back_populates="pool", cascade="all, delete-orphan")

class WatchStock(Base):
    __tablename__ = "watch_stock"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    pool_id = Column(String(36), ForeignKey("watch_pool.id"), nullable=False)
    ts_code = Column(String(16), nullable=False)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    added_price = Column(Float)
    source = Column(String(16), nullable=False, default="manual")
    monitor_status = Column(String(16), nullable=False, default="monitoring")
    note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    pool = relationship("WatchPool", back_populates="stocks")
    __table_args__ = (UniqueConstraint("pool_id", "ts_code", name="uq_pool_stock"),)
```

**步骤 2：提交**

```bash
git add backend/app/models/pool.py && git commit -m "feat: 添加 WatchPool 和 WatchStock 模型"
```

---

### 任务 1.6：ORM 模型 — monitor.py

**文件：**
- 创建：`backend/app/models/monitor.py`

**步骤 1：编写 MonitorRule + Alert 模型**

```python
from datetime import datetime
from sqlalchemy import Column, String, Boolean, JSON, DateTime, ForeignKey
from app.database import Base
from app.models.pool import gen_uuid

class MonitorRule(Base):
    __tablename__ = "monitor_rule"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    pool_id = Column(String(36), ForeignKey("watch_pool.id"), nullable=True)
    stock_id = Column(String(36), ForeignKey("watch_stock.id"), nullable=True)
    template_id = Column(String(32))
    params = Column(JSON)
    logic = Column(String(8), default="and")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alert"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    stock_id = Column(String(36), ForeignKey("watch_stock.id"), nullable=False)
    rule_id = Column(String(36), ForeignKey("monitor_rule.id"), nullable=False)
    ts_code = Column(String(16), nullable=False)
    trigger_date = Column(String(8), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    plan_id = Column(String(36), ForeignKey("trade_plan.id"), nullable=True)
    snapshot = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

**步骤 2：提交**

```bash
git add backend/app/models/monitor.py && git commit -m "feat: 添加 MonitorRule 和 Alert 模型"
```

---

### 任务 1.7：ORM 模型 — trade.py

**文件：**
- 创建：`backend/app/models/trade.py`

**步骤 1：编写 TradePlan + TradeDetail 模型**

```python
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.pool import gen_uuid

class TradePlan(Base):
    __tablename__ = "trade_plan"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    ts_code = Column(String(16), nullable=False)
    stock_name = Column(String(32))
    plan_type = Column(String(16), nullable=False)
    risk_level = Column(Integer, nullable=False, default=3)
    status = Column(String(16), nullable=False, default="pending")
    trigger_strategy = Column(Text)
    alert_id = Column(String(36), nullable=True)
    event_note = Column(Text)
    action_suggestion = Column(String(16))
    planned_buy_price = Column(Float)
    target_price = Column(Float)
    stop_loss_price = Column(Float)
    risk_reward_ratio = Column(Float)
    position_plan = Column(String(32))
    actual_pnl = Column(Float)
    review_summary = Column(Text)
    lessons_learned = Column(Text)
    note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    details = relationship("TradeDetail", back_populates="plan", cascade="all, delete-orphan")

class TradeDetail(Base):
    __tablename__ = "trade_detail"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    plan_id = Column(String(36), ForeignKey("trade_plan.id"), nullable=False)
    trade_date = Column(String(8), nullable=False)
    trade_time = Column(String(8))
    direction = Column(String(4), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    commission = Column(Float, default=0)
    stamp_tax = Column(Float, default=0)
    exec_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    plan = relationship("TradePlan", back_populates="details")
```

**步骤 2：提交**

```bash
git add backend/app/models/trade.py && git commit -m "feat: 添加 TradePlan 和 TradeDetail 模型"
```

---

### 任务 1.8：模型汇总导出

**文件：**
- 修改：`backend/app/models/__init__.py`

**步骤 1：导出所有模型**

```python
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule, Alert
from app.models.trade import TradePlan, TradeDetail

__all__ = [
    "StockBasic", "DailyQuote",
    "WatchPool", "WatchStock",
    "MonitorRule", "Alert",
    "TradePlan", "TradeDetail",
]
```

**步骤 2：验证建表**

```bash
python -c "from app.database import init_db; init_db(); print('All 8 tables created')"
```

**步骤 3：提交**

```bash
git add -A && git commit -m "feat: 汇总导出所有 ORM 模型，验证 8 张表建表"
```

---

### 任务 1.9：Tushare 适配层

**文件：**
- 创建：`backend/app/services/tushare_adapter.py`

**步骤 1：编写 TushareAdapter**

```python
import tushare as ts
import pandas as pd
from app.config import TUSHARE_TOKEN

class TushareAdapter:
    def __init__(self):
        self._pro = None

    @property
    def pro(self):
        if self._pro is None:
            self._pro = ts.pro_api(TUSHARE_TOKEN)
        return self._pro

    def get_stock_basic(self, ts_code: str = None) -> pd.DataFrame:
        params = {"exchange": "", "list_status": "L",
                  "fields": "ts_code,symbol,name,area,industry,market,list_date,list_status"}
        if ts_code:
            params["ts_code"] = ts_code
        return self.pro.stock_basic(**params)

    def get_daily(self, ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        params = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.pro.daily(**params)

tushare_adapter = TushareAdapter()
```

**步骤 2：提交**

```bash
git add backend/app/services/tushare_adapter.py && git commit -m "feat: 添加 Tushare 适配层"
```

---

### 任务 1.10：统一错误处理

**文件：**
- 创建：`backend/app/exceptions.py`

**步骤 1：编写异常类和处理器**

```python
from fastapi import Request
from fastapi.responses import JSONResponse

class AppError(Exception):
    def __init__(self, code: int, message: str, detail: str = None, status_code: int = 400):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code

async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )
```

**步骤 2：提交**

```bash
git add backend/app/exceptions.py && git commit -m "feat: 添加统一错误处理"
```

---

### 任务 1.11：后台任务基础设施

**文件：**
- 创建：`backend/app/tasks/background.py`

**步骤 1：编写后台任务管理**

```python
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TaskStatus:
    id: str
    type: str
    status: str = "running"
    progress: float = 0.0
    message: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

executor = ThreadPoolExecutor(max_workers=2)
task_registry: dict[str, TaskStatus] = {}

def submit_task(task_type: str, fn, *args, **kwargs) -> str:
    task_id = str(uuid.uuid4())
    task_registry[task_id] = TaskStatus(id=task_id, type=task_type)

    def wrapper():
        try:
            fn(task_id, *args, **kwargs)
            task_registry[task_id].status = "completed"
            task_registry[task_id].progress = 1.0
        except Exception as e:
            task_registry[task_id].status = "failed"
            task_registry[task_id].message = str(e)

    executor.submit(wrapper)
    return task_id

def get_task_status(task_id: str) -> TaskStatus | None:
    return task_registry.get(task_id)
```

**步骤 2：提交**

```bash
git add backend/app/tasks/background.py && git commit -m "feat: 添加后台任务线程池基础设施"
```

---

### 任务 1.12：FastAPI 入口

**文件：**
- 创建：`backend/app/main.py`

**步骤 1：编写 main.py**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.exceptions import AppError, app_error_handler

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="量化交易系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
```

**步骤 2：验证**

```bash
cd backend && uvicorn app.main:app --reload --port 8000
# 访问 http://localhost:8000/api/health 确认返回 {"status": "ok"}
# 访问 http://localhost:8000/docs 确认 Swagger UI 可用
```

**步骤 3：提交**

```bash
git add -A && git commit -m "feat: 完成 Phase 1 — 项目骨架、数据库、Tushare 适配层"
```

---

## Phase 2：观察池 + 数据同步

### 任务 2.1：观察池 Pydantic schemas

**文件：**
- 创建：`backend/app/schemas/pool.py`

关键 schema：`PoolCreate`、`PoolUpdate`、`PoolOut`（含 stock_count）、`WatchStockCreate`、`WatchStockOut`、`WatchStockUpdate`、`CSVImportResult`。

**验证：** `python -c "from app.schemas.pool import PoolOut; print(PoolOut.model_json_schema())"`

---

### 任务 2.2：观察池路由 — 池子 CRUD

**文件：**
- 创建：`backend/app/routers/pools.py`

实现 5 个接口：
- `GET /api/pools` — 列表（含 stock_count）
- `POST /api/pools` — 创建
- `GET /api/pools/{id}` — 详情
- `PUT /api/pools/{id}` — 更新
- `DELETE /api/pools/{id}` — 删除（级联删除池内股票）

**验证：** 通过 Swagger UI 创建、查询、更新、删除池子。

---

### 任务 2.3：池内股票管理

**文件：**
- 修改：`backend/app/routers/pools.py`

添加 5 个接口：
- `GET /api/pools/{id}/stocks` — 池内股票列表（支持 keyword、monitor_status 筛选）
- `POST /api/pools/{id}/stocks` — 添加单只股票（自动查 stock_basic 填充名称）
- `PUT /api/pools/{id}/stocks/{stock_id}` — 更新（备注、监控状态）
- `DELETE /api/pools/{id}/stocks/{stock_id}` — 移除
- `POST /api/pools/{id}/stocks/import` — CSV 批量导入

**验证：** 添加股票、CSV 导入、列表筛选。

---

### 任务 2.4：数据同步服务

**文件：**
- 创建：`backend/app/services/sync_service.py`

实现：
- `sync_stock_info(ts_code)` — 同步单只股票基础信息（upsert stock_basic）
- `sync_daily(ts_code, days=250)` — 增量同步日线（查本地最新日期，只拉缺失）
- `sync_pool(task_id, pool_id, days=250)` — 同步整个池子（遍历池内股票，更新进度，完成后触发扫描）

**验证：** 手动调用同步函数，检查 stock_basic 和 daily_quote 是否有数据。

---

### 任务 2.5：同步 API 路由

**文件：**
- 创建：`backend/app/routers/sync.py`

实现 3 个接口：
- `POST /api/sync/pool/{pool_id}` — 提交池子同步任务
- `POST /api/sync/stock/{ts_code}` — 提交单只股票同步
- `GET /api/sync/status/{task_id}` — 查询任务状态

**验证：** 提交同步任务，轮询状态直到 completed。

---

### 任务 2.6：路由注册 + 联调

**文件：**
- 修改：`backend/app/main.py`

注册 pools 和 sync 路由。

**验证：** 完整流程——创建池子 → 添加股票 → 触发同步 → 查看同步状态 → 检查 daily_quote 有数据。

**提交：**

```bash
git add -A && git commit -m "feat: 完成 Phase 2 — 观察池 CRUD + CSV 导入 + 数据同步"
```

---

## Phase 3：监控提醒

### 任务 3.1：技术指标计算服务

**文件：**
- 创建：`backend/app/services/indicator.py`

实现：
- `calc_ma(df, n)` — 移动平均线
- `calc_macd(df)` — MACD（DIF、DEA、柱）
- `calc_rsi(df, period=14)` — RSI
- `calc_vol_ma(df, n=5)` — 成交量均线
- `calc_n_day_high(df, n)` — N 日最高

全部基于 pandas DataFrame 计算，输入为 daily_quote 查询结果。

**验证：** 单元测试 — 构造测试数据，验证 MA(5)、MACD 金叉、RSI 值。

---

### 任务 3.2：监控模板引擎

**文件：**
- 创建：`backend/app/services/monitor_engine.py`

实现：
- 6 个模板判定函数（ma_support、macd_golden、rsi_oversold、volume_shrink、breakout_high、price_threshold）
- `evaluate_rule(df, rule)` — 根据规则评估是否触发
- `scan_stock(db, watch_stock)` — 扫描单只股票
- `scan_pool(task_id, pool_id)` — 扫描整个池子
- `scan_all(task_id)` — 扫描所有池子

**验证：** 单元测试 — 构造触发和不触发的行情数据，验证判定结果。

---

### 任务 3.3：监控规则 schemas

**文件：**
- 创建：`backend/app/schemas/monitor.py`

关键 schema：`MonitorRuleCreate`、`MonitorRuleOut`、`MonitorRuleUpdate`、`AlertOut`、`TemplateInfo`。

---

### 任务 3.4：监控规则路由

**文件：**
- 创建：`backend/app/routers/monitor.py`

实现 9 个接口：
- `GET /api/monitor/templates` — 模板列表
- `GET /api/pools/{id}/rules` — 池级规则
- `POST /api/pools/{id}/rules` — 为池子添加规则
- `GET /api/stocks/{stock_id}/rules` — 股票级规则
- `POST /api/stocks/{stock_id}/rules` — 为股票添加规则
- `PUT /api/monitor/rules/{rule_id}` — 更新规则
- `DELETE /api/monitor/rules/{rule_id}` — 删除规则
- `POST /api/monitor/scan` — 手动触发全量扫描
- `POST /api/monitor/scan/{pool_id}` — 手动触发指定池扫描

---

### 任务 3.5：提醒路由

**文件：**
- 创建：`backend/app/routers/alerts.py`

实现 4 个接口：
- `GET /api/alerts` — 提醒列表（分页、状态筛选）
- `GET /api/alerts/{id}` — 提醒详情
- `PUT /api/alerts/{id}` — 更新状态
- `POST /api/alerts/{id}/create-plan` — 一键创建交易计划

---

### 任务 3.6：同步完成自动触发扫描

**文件：**
- 修改：`backend/app/services/sync_service.py`

在 `sync_pool` 完成后调用 `scan_pool`。

**验证：** 同步池子 → 检查是否自动生成 Alert。

**提交：**

```bash
git add -A && git commit -m "feat: 完成 Phase 3 — 监控规则引擎 + 6 模板 + 扫描 + 提醒"
```

---

## Phase 4：交易计划

### 任务 4.1：交易计划 schemas

**文件：**
- 创建：`backend/app/schemas/trade.py`

关键 schema：`TradePlanCreate`、`TradePlanUpdate`、`TradePlanOut`（含 details 和 pnl_summary）、`TradeDetailCreate`、`TradeDetailUpdate`、`TradeDetailOut`、`ReviewSubmit`。

盈亏比自动计算：`risk_reward_ratio = (target_price - planned_buy_price) / (planned_buy_price - stop_loss_price)`

---

### 任务 4.2：交易计划路由

**文件：**
- 创建：`backend/app/routers/plans.py`

实现 6 个接口：
- `GET /api/plans` — 列表（分页、状态/类型筛选）
- `POST /api/plans` — 创建（自动算盈亏比，从 stock_basic 填充 stock_name）
- `GET /api/plans/{id}` — 详情（含关联明细 + 盈亏汇总）
- `PUT /api/plans/{id}` — 更新
- `DELETE /api/plans/{id}` — 删除（级联删除明细）
- `PUT /api/plans/{id}/review` — 提交复盘

---

### 任务 4.3：交易明细路由

**文件：**
- 修改：`backend/app/routers/plans.py`（或独立 `details.py`）

实现 4 个接口：
- `GET /api/plans/{id}/details` — 明细列表
- `POST /api/plans/{id}/details` — 添加明细（自动算 amount，卖出自动算 stamp_tax）
- `PUT /api/details/{id}` — 更新
- `DELETE /api/details/{id}` — 删除

添加/删除明细后自动更新 `trade_plan.actual_pnl`（汇总所有卖出金额 - 买入金额 - 佣金 - 印花税）。

---

### 任务 4.4：仪表盘路由

**文件：**
- 创建：`backend/app/routers/dashboard.py`

实现 1 个接口：
- `GET /api/dashboard` — 返回 pool_summary、recent_alerts（最近 10 条）、active_plans（状态为 pending/active）

---

### 任务 4.5：路由注册 + 全量联调

**文件：**
- 修改：`backend/app/main.py`

注册所有路由：pools、sync、monitor、alerts、plans、dashboard。

**验证：** 完整流程——创建池子 → 添加股票 → 同步 → 设监控规则 → 手动扫描 → 查看提醒 → 从提醒创建交易计划 → 添加交易明细 → 提交复盘 → 仪表盘汇总。

**提交：**

```bash
git add -A && git commit -m "feat: 完成 Phase 4 — 交易计划 + 明细 + 复盘 + 仪表盘"
```

---

## Phase 5：前端

### 任务 5.1：前端项目初始化

**步骤：**

```bash
cd newQuant
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install antd @ant-design/icons axios react-router-dom
```

配置 `vite.config.ts`，添加 proxy 到后端 `http://localhost:8000`。

---

### 任务 5.2：布局组件

**文件：**
- 创建：`frontend/src/layouts/MainLayout.tsx`

使用 Ant Design `Layout`、`Menu`、`Sider`，4 个导航项：仪表盘、观察池、监控提醒、交易计划。监控提醒带 `Badge` 角标。

---

### 任务 5.3：API 客户端 + 类型定义

**文件：**
- 创建：`frontend/src/api/client.ts` — axios 实例，baseURL `/api`
- 创建：`frontend/src/api/pools.ts` — 观察池相关请求
- 创建：`frontend/src/api/sync.ts` — 同步相关
- 创建：`frontend/src/api/monitor.ts` — 监控相关
- 创建：`frontend/src/api/alerts.ts` — 提醒相关
- 创建：`frontend/src/api/plans.ts` — 交易计划相关
- 创建：`frontend/src/api/dashboard.ts` — 仪表盘
- 创建：`frontend/src/types/index.ts` — TypeScript 类型

---

### 任务 5.4：路由配置

**文件：**
- 修改：`frontend/src/App.tsx`

配置 6 个路由，全部嵌套在 MainLayout 中。

---

### 任务 5.5：仪表盘页面

**文件：**
- 创建：`frontend/src/pages/Dashboard/index.tsx`

统计卡片 + 最新提醒列表 + 活跃计划列表。使用 `Statistic`、`Card`、`Table`。

---

### 任务 5.6：观察池列表页面

**文件：**
- 创建：`frontend/src/pages/Pools/PoolList.tsx`

池子列表表格 + 新建弹窗（含默认监控条件配置）。

---

### 任务 5.7：池内详情页面

**文件：**
- 创建：`frontend/src/pages/Pools/PoolDetail.tsx`

股票表格（含现价列需同步后显示）+ 添加弹窗 + CSV 导入弹窗（含预览）+ 同步按钮 + 进度条 + 监控设置弹窗。

---

### 任务 5.8：监控提醒页面

**文件：**
- 创建：`frontend/src/pages/Alerts/index.tsx`

Tab 切换（待处理/已处理/已忽略）+ 提醒卡片 + 行情快照 + 操作按钮（创建计划/忽略）。

---

### 任务 5.9：交易计划列表页面

**文件：**
- 创建：`frontend/src/pages/Plans/PlanList.tsx`

状态 Tab + 计划表格 + 新建弹窗（完整表单）。

---

### 任务 5.10：计划详情页面

**文件：**
- 创建：`frontend/src/pages/Plans/PlanDetail.tsx`

交易逻辑区 + 价格目标区 + 交易明细表（含添加弹窗）+ 持仓汇总 + 复盘区。

---

### 任务 5.11：联调 + 修复

**验证：** 启动后端 + 前端，走通完整工作流。

**提交：**

```bash
git add -A && git commit -m "feat: 完成 Phase 5 — 前端全部页面 + 联调"
```

---

## 执行建议

**推荐 Subagent 驱动执行：** 每个任务分派独立 subagent，每完成一个任务做 spec + 质量双审查，逐步推进。

**后端优先：** Phase 1-4 全部是后端，可以通过 Swagger UI 验证，不依赖前端。Phase 5 前端可以在后端 API 全部就绪后一次性实现。
