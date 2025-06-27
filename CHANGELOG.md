# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Provider Functions Support**: Added comprehensive support for Terraform provider functions
  - New `tf.function` module with classes for defining provider functions:
    - `Parameter` class for function parameters with type constraints and validation options
    - `Return` class for function return types
    - `FunctionSignature` class for complete function signatures including variadic parameters
    - `CallContext` for passing diagnostics and context to function calls
    - `Function` protocol defining the interface for provider functions
  - Updated Provider interface to support functions:
    - Added `get_functions()` method to return list of supported function types
    - Added `new_function()` method to instantiate function instances
  - Implemented function RPC handlers in ProviderServicer:
    - `GetProviderSchema` now includes function definitions
    - `GetFunctions` RPC returns all function schemas
    - `CallFunction` RPC executes functions with full parameter validation, type encoding/decoding, error handling, and diagnostics support
  - Added comprehensive test coverage for all function-related functionality
  - Maintained 100% code coverage across the project

- **Invalid Field Value Error Diagnostics**: An error diagnostic is now emitted when an invalid field value
    is supplied (like invalid JSON to a json field). Previously, the plugin would crash.

### Changed

- Updated `GetFunctions` test to reflect the new implementation (no longer returns "not implemented" warning)