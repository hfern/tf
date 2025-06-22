# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the Python TF Plugin Framework - a Python library that enables writing Terraform/OpenTofu providers in Python. It abstracts away the complexity of interfacing with the TF type system, implementing the Go Plugin Protocol, and the TF Plugin Protocol.

## Common Development Commands

### Setup and Dependencies
```bash
make prepare-venv  # Install all dependencies via Poetry
```

### Code Quality
```bash
make format        # Auto-format code with ruff
make test-format   # Check formatting without changes
```

### Testing
```bash
make test          # Run all tests (format check, unit tests, type checking)
make test-python   # Run unit tests with coverage (requires 100% coverage)
make test-pyre     # Run type checking with Pyre
```

### Building
```bash
make build         # Build the package with Poetry
make doc           # Build Sphinx documentation
```

### Protocol Buffer Generation
```bash
make generate-tfproto  # Regenerate Python code from tfplugin.proto
```

### Running Individual Tests
```bash
poetry run python -m unittest tf.tests.test_provider.TestProviderClass.test_specific_method
```

## Architecture Overview

### Core Components

1. **Provider Framework** (`tf/provider.py`): Main service implementation for the gRPC-based Terraform Plugin Protocol. Handles all provider lifecycle operations.

2. **Type System** (`tf/types.py`): Python representations of Terraform's type system including primitives, collections, and the special Unknown type.

3. **Schema** (`tf/schema.py`): Defines how resources and data sources expose their configuration schema to Terraform.

4. **Interfaces** (`tf/iface.py`): Abstract base classes that users implement:
   - `Provider`: Main provider class
   - `Resource`: For managed resources (CRUD operations)
   - `DataSource`: For read-only data sources

5. **Protocol Layer** (`tf/gen/`): Auto-generated gRPC/protobuf code from Terraform's plugin protocol v6.5.

### Key Design Patterns

- **Context Objects**: Each operation (Create, Read, Update, Delete) receives a typed context object containing the request data and diagnostics collector.
- **Type Encoding/Decoding**: The framework handles automatic conversion between Python types and Terraform's msgpack-encoded type system.
- **Diagnostic Collection**: Errors and warnings are collected through a Diagnostics object rather than raising exceptions.
- **State Management**: Resource state is automatically encoded/decoded between Python dicts and Terraform's internal format.

### Testing Strategy

- 100% test coverage is enforced
- Tests use Python's unittest framework
- Each core module has a corresponding test file in `tf/tests/`
- Generated code (`tf/gen/`) is excluded from coverage

## Important Production Caveat

This framework is primarily intended for development, testing, and proof-of-concept work. Production deployment faces significant challenges because Terraform expects providers to be single binaries, while Python requires an interpreter and dependencies. See `docs/caveats.md` for detailed information about production considerations.