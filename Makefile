HIDE := @
TFPLUGIN_PROTO := tfplugin6.5.proto
POETRY := poetry
MODULE := tf

prepare-venv:
	$(HIDE)$(POETRY) install

format:
	# Format and sort imports with ruff
	$(HIDE)$(POETRY) run ruff format $(MODULE)
	$(HIDE)$(POETRY) run ruff check --fix $(MODULE)

test-format:
	$(HIDE)$(POETRY) run ruff format $(MODULE) --check
	$(HIDE)$(POETRY) run ruff check $(MODULE)

update-tfplugin-proto:
	$(HIDE)curl https://raw.githubusercontent.com/opentofu/opentofu/main/docs/plugin-protocol/$(TFPLUGIN_PROTO) > tfplugin.proto

generate-tfproto:
	$(HIDE)rm -rf ./tf/gen
	$(HIDE)mkdir -p ./tf/gen
	$(HIDE)$(POETRY) run python -m grpc_tools.protoc \
		-Itf/gen=. \
		--python_out=. \
		--grpc_python_out=. \
		--pyi_out=. \
		--proto_path=. \
		tfplugin.proto
	$(HIDE)echo "" > tf/gen/__init__.py

test-python:
	$(HIDE)$(POETRY) run coverage run -m unittest discover
	$(HIDE)$(POETRY) run coverage report -m --fail-under=100

test-pyre:
	$(HIDE)$(POETRY) run pyre check

test: test-format test-python test-pyre
	$(HIDE)echo "All tests passed"
