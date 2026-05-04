SHELL := /bin/bash

.PHONY: install dev doctor demo-cast demo-storyboard clean

install:
	python -m pip install -e .

dev:
	python -m pip install -e . && python -m pip install ruff pytest

doctor:
	videogen doctor

# Quick smoke test: dry-run cast init without uploading.
demo-cast:
	videogen cast init --project demo --no-upload

# Validate a hand-crafted storyboard.json (drop one in projects/demo/storyboard.json first).
demo-storyboard:
	videogen storyboard validate --project demo
	videogen storyboard show --project demo

clean:
	rm -rf projects/demo build dist *.egg-info src/*.egg-info
