.PHONY: webui-demo-state webui-dev webui-demo lock

lock:
	./scripts/lock.sh

webui-demo-state:
	python3 webui/scripts/seed_demo_state.py

webui-dev:
	npm --prefix webui run dev

webui-demo: webui-dev
