UI_APP := mimir/ui/app

.PHONY: help ui ui-dev ui-clean test install build

help:
	@echo "make ui        rebuild the annotate UI into mimir/ui/dist (dev loop, no reinstall)"
	@echo "make ui-dev    run the Vite dev server against a local mimir server on :4141"
	@echo "make ui-clean  remove the built UI"
	@echo "make test      run the Python test suite"
	@echo "make build     build the wheel/sdist (builds the UI via hatch_build.py)"
	@echo "make install   uv tool install --force this checkout"

# Dev loop: rebuild the UI in place. `mimir annotate` serves mimir/ui/dist
# directly, so an editable/`uv run` checkout picks this up with no reinstall.
ui:
	cd $(UI_APP) && bun install && bun run build

ui-dev:
	cd $(UI_APP) && bun install && bun run dev

ui-clean:
	rm -rf mimir/ui/dist

test:
	uv run pytest tests/ -q

build:
	uv build

install:
	uv tool install --force --reinstall .
