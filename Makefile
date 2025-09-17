HIDE := @
TFPLUGIN_PROTO := tfplugin6.5.proto
POETRY := poetry
MODULE := tf
FORMATTABLE_SOURCES := $(MODULE) e2e docs/examples

prepare-venv:
	$(HIDE)$(POETRY) install

format:
	# Format and sort imports with ruff
	$(HIDE)$(POETRY) run ruff format $(FORMATTABLE_SOURCES)
	$(HIDE)$(POETRY) run ruff check --fix $(FORMATTABLE_SOURCES)

test-format:
	$(HIDE)$(POETRY) run ruff format $(FORMATTABLE_SOURCES) --check
	$(HIDE)$(POETRY) run ruff check $(FORMATTABLE_SOURCES)

update-tfplugin-proto:
	$(HIDE)curl https://raw.githubusercontent.com/opentofu/opentofu/main/docs/plugin-protocol/$(TFPLUGIN_PROTO) > tfplugin.proto
	$(HIDE)curl https://raw.githubusercontent.com/hashicorp/go-plugin/df457caa367789011bc0571ea1d5712b52f3fc88/internal/plugin/grpc_stdio.proto > grpc_stdio.proto
	$(HIDE)curl https://raw.githubusercontent.com/hashicorp/go-plugin/df457caa367789011bc0571ea1d5712b52f3fc88/internal/plugin/grpc_controller.proto > grpc_controller.proto

generate-tfproto:
	$(HIDE)rm -rf ./tf/gen
	$(HIDE)mkdir -p ./tf/gen
	$(HIDE)$(POETRY) run python -m grpc_tools.protoc \
		-Itf/gen=. \
		--python_out=. \
		--grpc_python_out=. \
		--pyi_out=. \
		--proto_path=. \
		tfplugin.proto grpc_stdio.proto grpc_controller.proto
	$(HIDE)echo "" > tf/gen/__init__.py

test-python:
	$(HIDE)$(POETRY) run coverage run -m unittest discover
	$(HIDE)$(POETRY) run coverage report -m --fail-under=100

test-pyre:
	$(HIDE)$(POETRY) run pyre check

test: test-format test-python test-pyre
	$(HIDE)echo "All tests passed"

build:
	$(HIDE)$(POETRY) build

doc:
	$(HIDE)$(POETRY) run sphinx-build -M html ./docs ./docs/_build -W


clean:
	$(HIDE)rm -rf ./dist
	$(HIDE)rm -rf ./docs/_build
