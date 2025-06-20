# Provider Functions

Provider functions allow you to expose custom functions that can be called from Terraform configurations. Functions are useful for data transformation, validation, and other operations that don't fit into the resource or data source paradigms.

## Overview

Functions in Terraform providers:
- Accept zero or more typed parameters
- Return a single typed value
- Can report errors through diagnostics
- Support variadic parameters (optional)
- Are stateless and side-effect free

## Creating a Function

To create a provider function, implement the `Function` protocol:

```python
from tf.function import Function, FunctionSignature, Parameter, Return, CallContext
from tf.types import String, Number, Bool
from typing import Any, List

class UppercaseFunction(Function):
    def __init__(self, provider):
        self.provider = provider
    
    @classmethod
    def get_name(cls) -> str:
        """Return the function name as it will appear in Terraform"""
        return "uppercase"
    
    @classmethod
    def get_signature(cls) -> FunctionSignature:
        """Define the function's parameters and return type"""
        return FunctionSignature(
            parameters=[
                Parameter(
                    name="input",
                    type=String(),
                    description="The string to convert to uppercase",
                    allow_null_value=False,
                    allow_unknown_values=False,
                )
            ],
            return_type=Return(type=String()),
            summary="Convert a string to uppercase",
            description="This function converts the input string to uppercase letters",
        )
    
    def call(self, ctx: CallContext, arguments: List[Any]) -> Any:
        """Execute the function with the given arguments"""
        input_string = arguments[0]
        return input_string.upper()
```

## Function Components

### Parameters

Parameters define the inputs to your function:

```python
Parameter(
    name="param_name",
    type=String(),  # Can be any TfType
    description="Human-readable description",
    description_kind=TextFormat.Markdown,  # Optional, defaults to Markdown
    allow_null_value=False,  # Whether null values are allowed
    allow_unknown_values=False,  # Whether unknown values are allowed
)
```

### Return Type

The return type specifies what type of value the function returns:

```python
Return(type=String())  # Can be any TfType
```

### Function Signature

The signature combines parameters, return type, and metadata:

```python
FunctionSignature(
    parameters=[...],  # List of Parameter objects
    return_type=Return(...),  # Return type
    variadic_parameter=Parameter(...),  # Optional variadic parameter
    summary="Short description",
    description="Detailed description",
    description_kind=TextFormat.Markdown,
    deprecation_message="Message if deprecated",
)
```

## Variadic Functions

Functions can accept a variable number of arguments using a variadic parameter:

```python
class ConcatFunction(Function):
    @classmethod
    def get_signature(cls) -> FunctionSignature:
        return FunctionSignature(
            parameters=[
                Parameter(name="separator", type=String()),
            ],
            variadic_parameter=Parameter(
                name="values",
                type=String(),
                description="Values to concatenate",
            ),
            return_type=Return(type=String()),
            summary="Concatenate strings with a separator",
        )
    
    def call(self, ctx: CallContext, arguments: List[Any]) -> Any:
        separator = arguments[0]
        values = arguments[1:]  # All remaining arguments
        return separator.join(values)
```

## Error Handling

Functions can report errors through the diagnostics system:

```python
def call(self, ctx: CallContext, arguments: List[Any]) -> Any:
    value = arguments[0]
    
    if value < 0:
        ctx.diagnostics.add_error(
            "Invalid input",
            "Value must be non-negative"
        )
        return 0  # Return a safe default
    
    return value * 2
```

If a function adds an error diagnostic, Terraform will treat the function call as failed.

## Complex Example

Here's a more complex example that validates and formats a phone number:

```python
import re

class FormatPhoneFunction(Function):
    def __init__(self, provider):
        self.provider = provider
    
    @classmethod
    def get_name(cls) -> str:
        return "format_phone"
    
    @classmethod
    def get_signature(cls) -> FunctionSignature:
        return FunctionSignature(
            parameters=[
                Parameter(
                    name="phone",
                    type=String(),
                    description="Phone number to format",
                ),
                Parameter(
                    name="country_code",
                    type=String(),
                    description="Country code (e.g., 'US', 'UK')",
                ),
            ],
            return_type=Return(type=String()),
            summary="Format a phone number",
            description="Formats a phone number according to the specified country's conventions",
        )
    
    def call(self, ctx: CallContext, arguments: List[Any]) -> Any:
        phone = arguments[0]
        country_code = arguments[1]
        
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', phone)
        
        if country_code == "US":
            if len(digits) != 10:
                ctx.diagnostics.add_error(
                    "Invalid phone number",
                    f"US phone numbers must have 10 digits, got {len(digits)}"
                )
                return phone  # Return original on error
            
            # Format as (XXX) XXX-XXXX
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        
        elif country_code == "UK":
            if len(digits) != 11 or not digits.startswith("0"):
                ctx.diagnostics.add_error(
                    "Invalid phone number",
                    "UK phone numbers must have 11 digits and start with 0"
                )
                return phone
            
            # Format as 0XXXX XXXXXX
            return f"{digits[:5]} {digits[5:]}"
        
        else:
            ctx.diagnostics.add_warning(
                "Unknown country code",
                f"Country code '{country_code}' is not supported, returning unformatted"
            )
            return phone
```

## Registering Functions with Your Provider

Add your functions to the provider's `get_functions()` method:

```python
from tf.iface import Provider
from typing import Type, List

class MyProvider(Provider):
    # ... other provider methods ...
    
    def get_functions(self) -> List[Type[Function]]:
        """Return all function types supported by this provider"""
        return [
            UppercaseFunction,
            ConcatFunction,
            FormatPhoneFunction,
        ]
```

## Using Functions in Terraform

Once implemented, your functions can be used in Terraform configurations:

```hcl
# Using a simple function
output "uppercase_name" {
  value = provider::myprovider::uppercase("hello world")
}

# Using a variadic function
output "joined_values" {
  value = provider::myprovider::concat(", ", "apple", "banana", "cherry")
}

# Using a function with error handling
output "formatted_phone" {
  value = provider::myprovider::format_phone("5551234567", "US")
  # Returns: (555) 123-4567
}
```

## Best Practices

1. **Keep functions pure**: Functions should not have side effects or modify external state
2. **Validate inputs**: Check parameter values and provide clear error messages
3. **Handle edge cases**: Consider null values, empty strings, and boundary conditions
4. **Document thoroughly**: Provide clear descriptions for the function and all parameters
5. **Use appropriate types**: Choose the most specific type for parameters and return values
6. **Test comprehensively**: Write unit tests covering normal cases, edge cases, and error conditions

## Type Compatibility

Functions work with all Terraform types:
- Primitives: `String()`, `Number()`, `Bool()`
- Collections: `List()`, `Map()`, `Set()`
- Complex types: `Object()` with nested attributes
- Special types: `DynamicPseudoType()` for any-type parameters

See the [types documentation](elements.md#types) for more details on available types.