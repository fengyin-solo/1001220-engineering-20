.PHONY: install build backend frontend start check stop

# 本地事故链路联调三步走：make install -> make build -> make start，然后 make check

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

build:
	@[ -x backend/.venv/bin/pip ] || { echo "后端依赖未安装，请先执行 make install"; exit 1; }
	cd backend && .venv/bin/pip install -q -r requirements.txt
	cd frontend && npm run build

# 一条命令拉起前后端（构建产物模式）：依赖缺失/端口占用会直接报错退出
start:
	./scripts/start.sh

# 理赔完成后的可复现检查：调接口走通 上报->核定->理赔 并核对结论
check:
	python3 scripts/check_accident_flow.py

# 日常热更新调试仍然可以两边分别起
backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 按 start.sh 记下的 PID 停服，不依赖 lsof/ss
stop:
	@for f in .run/backend.pid .run/frontend.pid; do \
	  if [ -f "$$f" ]; then kill "$$(cat $$f)" 2>/dev/null || true; rm -f "$$f"; fi; \
	done
