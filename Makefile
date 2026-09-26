.PHONY: install backend frontend dev-up dev-down verify seed-demo build-frontend

install:
	python3 scripts/ensure-backend-env.py
	cd frontend && npm install

backend:
	./backend/run.sh

frontend:
	cd frontend && npm run dev

# 一条命令：预检 + 安装依赖 + 构建前端 + 拉起前后端 + 灌入事故理赔示例链路
dev-up:
	scripts/dev-up.sh

# 停止 dev-up 拉起的前后端
dev-down:
	scripts/dev-down.sh

# 只重新灌一遍「待上报 -> 已理赔」的示例事故（要求后端已在运行）
seed-demo:
	scripts/seed-accident-demo.sh

# 理赔结论与接口返回的一致性复核
verify:
	scripts/verify-claim.sh

build-frontend:
	cd frontend && npm run build
