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
│   └── app/seed.py           内存数据仓库与示例数据
├── scripts/                  本地联调脚本
│   ├── dev-up.sh             预检 + 装依赖 + 构建 + 双服务 + 灌事故链路
│   ├── dev-down.sh           停止 dev-up 拉起的前后端
│   ├── seed-accident-demo.sh 调接口走一遍「待上报 → 已理赔」
│   ├── verify-claim.py       理赔结论与接口返回的一致性复核
│   └── ensure-backend-env.py 后端虚拟环境准备（venv / get-pip 回退）
├── Makefile                  make dev-up / dev-down / verify 入口
├── .gitignore
└── docker-compose.yml
```

## 启动

### 一条命令拉起联调环境（推荐）

事故记录的「事故上报 → 损失核定 → 保险理赔」需要前后端一起验，推荐直接用脚本收口：

```bash
make dev-up        # 等价于 scripts/dev-up.sh
```

脚本会按顺序完成：

1. 预检 `python3`（含 venv）、`node 18+`、`npm`、`curl`，并检查 8000 / 5173 端口；
   依赖缺失或端口被占用时会直接报出原因和处理办法（支持 `apt` 装包提示与
   `get-pip.py` 在线引导两种回退）；
2. 准备后端虚拟环境（`backend/.venv`）并安装 `requirements.txt`，
   安装前端依赖（`frontend/node_modules`）；
3. 跑一遍前端构建（`vue-tsc` 类型检查 + `vite build`），编译问题在起服务前暴露；
4. 后台拉起后端 uvicorn 与前端 vite dev server，分别通过健康检查；
5. 调用接口创建一条示例事故并走完整链路：
   `待上报 → 已上报 → 待理赔 → 理赔中 → 已理赔`
   （事故编号、事故类型、损失金额、赔付金额、理赔结论都有值），
   记录写入 `.run/accident-demo.json`。

启动后：

- 事故记录页面：http://127.0.0.1:5173/accident
- 后端接口：http://127.0.0.1:8000/api/accident
- 停止服务：`make dev-down`（按 PID / 监听端口兜底回收，不留脱管进程）
- 换端口：`BACKEND_PORT=8010 FRONTEND_PORT=5180 make dev-up`

服务运行期间重复灌一条链路示例数据：`make seed-demo`。

### 理赔复核（可复现检查）

理赔完成后，用检查脚本确认「理赔结论」与接口返回一致（退出码 0 表示通过，可放进 CI）：

```bash
make verify        # scripts/verify-claim.sh，同时核对后端直连与前端 /api 代理
```

核对项：事故终态为「已理赔」、赔付金额与理赔结论齐全、赔付金额不超过核定损失金额、
后端直连与前端代理返回逐字段一致；配合 `.run/accident-demo.json` 还会比对
损失金额 12000 / 赔付金额 9600 / 结论「保险已赔付」。

也可指定任意事故复核：

```bash
python3 scripts/verify-claim.py --id 5 \
  --backend-base-url http://127.0.0.1:8000 \
  --expect-loss 32000 --expect-payout 25600 --expect-conclusion 保险已赔付
```

### 手工分别启动（原有方式，仍然保留）

后端：

```bash
make backend       # 或 cd backend && ./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

前端：

```bash
make frontend      # 或 cd frontend && npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

### 事故记录状态链路

| 阶段 | 动作 | 状态流转 | 写入字段 |
| --- | --- | --- | --- |
| 事故上报 | 上报事故 | 待上报 → 已上报 | 发生时间、事故描述 |
| 损失核定 | 损失核定 | 已上报 → 待理赔 | 损失金额（必填、需为非负数字） |
| 保险理赔 | 启动理赔 | 待理赔 → 理赔中 | 保险理赔（报案/审核说明） |
| 保险理赔 | 理赔到账 | 理赔中 → 已理赔 | 赔付金额、理赔结论（必填，且赔付 ≤ 损失） |

动作必须按顺序执行，跳步、重复执行、金额非法或赔付超额都会被服务层拦下并返回原因。
内置示例数据（`backend/app/seed.py` 的 accident 表）覆盖全部五个状态，其中包含
待理赔与已理赔记录，页面和脚本起服务即可看到。

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
| 事故记录 | `accident` | 事故记录 | 事故编号、关联任务、事故类型 |
| 途中核查 | `roadcheck` | 途中核查 | 核查编号、关联调度、核查时间 |
| 车厢清洗 | `clean2` | 清洗记录 | 清洗编号、清洗车辆、清洗方式 |
| 合作合同 | `contract2` | 运输合同 | 合同编号、签约双方、合同类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
