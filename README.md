# 冷链物流运输管理平台

面向冷链运输全程温控、车辆调度、门到门配送、温度异常处置、签收回单与运力结算的冷链运输管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── scripts/
│   ├── start.sh              一条命令拉起前后端（依赖/端口预检查）
│   └── check_accident_flow.py 事故上报→损失核定→保险理赔 链路检查
├── Makefile                  install / build / start / check 入口
├── .gitignore
└── .env.example
```

## 本地启动流程（推荐）

事故记录链路（事故上报 → 损失核定 → 保险理赔）需要前后端一起验，统一用 Makefile 收口：

```bash
make install   # 首次：后端建 venv 装依赖、前端 npm install
make build     # 前端 vue-tsc 类型检查并构建到 frontend/dist
make start     # 一条命令同时拉起后端 :8000 与前端 :5173（构建产物模式）
```

启动成功后：

- 前端：<http://127.0.0.1:5173/>，事故记录页：<http://127.0.0.1:5173/accident>
- 后端：<http://127.0.0.1:8000/api/health>
- 前端的 `/api` 请求由 vite preview 代理到后端，无需改地址
- 日志在 `.run/backend.log`、`.run/frontend.log`，`Ctrl+C` 同时停两端；也可 `make stop`

启动前的预检查会直接报错退出（不会留下半截进程）：

- 缺少 `python3` / `npm`：提示先安装运行时
- `backend/.venv` 或 `frontend/node_modules` 缺失：提示先执行 `make install`
- `frontend/dist` 不存在：提示先执行 `make build`
- `8000` / `5173` 被占用：提示端口冲突，并尽量打印占用进程信息

> 数据同步：后端目前是内存数据仓库，每次启动都会按 `backend/app/seed.py`
> 重新写入示例数据，因此改完种子数据只需重启后端（重新 `make start`）即生效，
> 不存在忘记同步数据库的问题。

### 事故链路联调与理赔结论核对

示例数据预置了四条事故，状态覆盖 **待上报 → 已上报 → 理赔中 → 已结案**，
每条都带事故编号、事故类型、损失金额，已结案一条带最终理赔结论（见
`backend/app/seed.py` 的 `accident` 表）。

- 页面联调：打开事故记录页，对「待上报」记录依次点
  **上报事故 → 启动理赔 → 结案归档**；列表与页脚会实时反映状态和后端返回的原因。
- 可复现检查：服务起着时，另开终端执行

  ```bash
  make check
  ```

  脚本（`scripts/check_accident_flow.py`）会：
  1. 校验示例数据覆盖四个状态且事故编号/事故类型/损失金额齐全、已结案记录带理赔结论；
  2. 通过接口新建一条事故（固定编号 `ACCI-CHECK`、初始损失 20000），依次执行
     上报事故、启动理赔（核定损失 18000）、结案归档（写入理赔结论）；
  3. 再用 GET 详情、`status=已结案` 列表过滤、按编号检索三个读接口，
     核对状态、核定金额、理赔结论与动作返回完全一致。

  全部通过以退出码 0 结束；任一项不一致会打印 `✗` 明细并以非 0 退出，可直接进 CI。
  后端不在默认地址时可用 `API_BASE=http://host:port make check` 覆盖。

### 分开启动（热更新调试）

```bash
make backend    # backend/run.sh：自动建 venv、装依赖后跑 uvicorn :8000
make frontend   # frontend：vite dev server :5173，/api 代理到 :8000
```

后端健康检查：`curl http://127.0.0.1:8000/api/health`。
dev server 不会自动打开浏览器，`/api` 同样代理到 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 车辆档案 | `fleet` | 冷链车 | 车辆编号、车牌号码、车型类别 |
| 司机管理 | `driver` | 驾驶员 | 驾驶员编号、驾驶员姓名、驾驶证号 |
| 运输委托 | `order` | 运输委托单 | 委托编号、委托方、起运地址 |
| 运力调度 | `dispatch3` | 调度任务 | 调度编号、关联委托、指派车辆 |
| 温控监测 | `temp` | 温度记录 | 记录编号、关联调度、温区编号 |
| 门到门配送 | `door` | 配送任务 | 任务编号、关联调度、配送站点 |
| 回单管理 | `returntrip` | 回执单 | 回单编号、关联任务、签收方 |
| 异常处置 | `abnormal2` | 异常记录 | 异常编号、异常类型、关联任务 |
| 续运中转 | `renew` | 中转记录 | 中转编号、关联任务、中转站点 |
| 制冷机组 | `refriger` | 制冷机组 | 机组编号、所属车辆、机组型号 |
| 温控箱体 | `box` | 温控箱体 | 箱体编号、箱体类型、内部容积 |
| 运输路线 | `route` | 路线方案 | 路线编号、出发地、目的地 |
| 温感器管理 | `sensor` | 温度传感器 | 传感器编号、所属车辆、传感器型号 |
| 运输费用 | `cost` | 费用记录 | 费用编号、关联任务、费用类别 |
| 委托方管理 | `client2` | 委托方 | 委托方编号、委托方名称、企业类别 |
| 出车检查 | `checkin` | 检查记录 | 检查编号、检查车辆、检查日期 |
| 事故记录 | `accident` | 事故记录 | 事故编号、事故类型、损失金额、保险理赔 |
| 途中核查 | `roadcheck` | 途中核查 | 核查编号、关联调度、核查时间 |
| 车厢清洗 | `clean2` | 清洗记录 | 清洗编号、清洗车辆、清洗方式 |
| 合作合同 | `contract2` | 运输合同 | 合同编号、签约双方、合同类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
