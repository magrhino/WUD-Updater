.PHONY: webui-demo-state webui-dev webui-demo lock

lock:
	pip-compile pyproject.toml -o requirements.txt

webui-demo-state:
	python3 webui/scripts/seed_demo_state.py

webui-dev:
	npm --prefix webui run dev

webui-demo: webui-dev
