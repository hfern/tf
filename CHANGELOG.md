# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Descriptions and Deprecation Fields for Schemas and Blocks**:
  - Added `description`, `description_kind`, and `deprecated` fields to Schema and Block. This allows resource, data sources, and providers to specify these fields for documentation.
- **End-to-End Tests**:
  - Added comprehensive end-to-end tests against OpenTofu. This ensures that providers, resources, and data sources work correctly against the real OpenTofu CLI.
- **Tutorial**:
  - Added a tutorial to the documentation to help new users get started with writing a provider using `tf`.
- **Field Names for Encoding Errors**:
  - Field names are now printed in rare cases where field values first pass validation/decoding,
        but later catastrophically fail to encode or semantically compare.
        These cases are generally bugs in `tf` itself, but the field names help identify the problematic fields.

### Fixed
- **Set Crashes**:
  - Fixed crashes when using `Set` types without either provided or default values.
        This fixes the general case for complex types with custom semantic equality functions (only `Set` currently).
- **Certificate Generation Failure**:
  - Fixed certificate generation failure on systems with a positive UTC offset (e.g. UTC+2).

## 1.1.0

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

### Fixed

- **Critical Provider Protocol Fixes**:
  - Fixed `GetMetadata` RPC to return proper server capabilities instead of UNIMPLEMENTED error
    - Now correctly advertises `plan_destroy` and `get_provider_schema_optional` capabilities
  - Fixed `StopProvider` RPC to return proper response for graceful shutdown
  - Fixed shutdown interceptor to monitor the correct method (`/tfplugin6.Provider/StopProvider`)
  - Added proper server shutdown with `server.stop()` call to prevent 2-second timeout delays
  - Implemented `GRPCController` service required by go-plugin framework with `Shutdown` method
    - This eliminates "Method not found!" errors and allows proper plugin lifecycle management
  - Added `GRPCStdio` service to eliminate "Method not found!" debug messages
  - Populated `provider_meta` field with valid empty schema to eliminate "No provider meta schema returned" debug warning
    - Previously caused nil pointer dereference when set to empty pb.Schema()
    - Now returns properly initialized Schema with empty Block
  - These fixes eliminate the "plugin failed to exit gracefully" warnings and reduce terraform plan time by ~6 seconds

### Performance

- **Runtime Performance Improvements**:
  - Made gRPC logging configurable via `TF_PLUGIN_DEBUG` environment variable to reduce overhead in production
  - Optimized `NormalizedJson.semantically_equal()` to avoid unnecessary re-encoding of JSON values
  - Fixed inefficient `Set.semantically_equal()` implementation that had O(n²) complexity
  - Added caching for provider and resource schemas to avoid repeated schema generation
  - Optimized state encoding preservation logic to reduce redundant operations
  - Reduced unnecessary `deepcopy` usage throughout the codebase for better memory efficiency

- **Startup Performance Improvements**:
  - Implemented lazy loading for expensive imports (grpc ~22.5ms, cryptography ~20ms, protobuf ~9-21ms)
  - Added SSL certificate caching to avoid regenerating certificates on every startup (~5-14ms saved)
  - SSL certificates now cached for 7 days in `~/.cache/tf-python-provider/`
  - Added startup timing diagnostics via `TF_PLUGIN_TIMING=1` environment variable for performance profiling
  - Total startup time reduced from ~105-120ms to ~30-40ms on subsequent runs with cached certificates