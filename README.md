# Python TF Plugin Framework

This package acts as an interface for writing a Terraform/OpenTofu ("TF")
provider in Python.
This package frees you of the toil of interfacing with the TF type system,
implementing the Go Plugin Protocol, implementing the TF Plugin Protocol, and
unbundling compound API calls.

Instead, you can simply implement Create, Read, Update, and Delete operations
using idiomatic Python for each of the resource types you want to support.

## Installation

This package is available on PyPI, and can be installed using pip.

```bash
pip install tf
```

## Using the Framework

There are three primary interfaces in this framework:

1. **Provider** - By implementing this interface, you can define
    a new provider. This defines its own schema, and supplies
    resource and data source classes to the framework.
1. **Data Source** - This interface is used to define a data source, which
    is a read-only object that can be used to query information
    from the provider or backing service.
1. **Resource** - This interface is used to define a resource, which
    is a read-write object that can be used to create, update,
    and delete resources in the provider or backing service.
    Resources represent full "ownership" of the underlying object.
    This is the primary type you will use to interact with the system.

To use this interface, create one class implemented `Provider`, and any number
of classes implementing `Resource` and `DataSource`.

Then, call `run_provider` with an instance of your provider class. A basic
main function might look like:

```python
import sys

from tf import runner
from mypackage import MyProvider


def main():
    provider = MyProvider()
    runner.run_provider(provider, sys.argv)
```

### Entry Point Name

TF requires a specific naming convention for the provider. Your executable
must be named in the form of `terraform-provider-<providername>`.
This means that you must your [entrypoint](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
similarly.

```toml
[project.scripts]
terraform-provider-myprovider = "mypackage.main:main"
```

### TF Developer Overrides

In order to get TF to use your provider, you must tell TF to run your provider from a custom path.

This is done by editing the `~/.terraformrc` or `~/.tofurc` file,
and setting the path to your virtual environment's `bin` directory (which contains the `terraform-provider-myprovider` script).

```hcl
provider_installation {
  dev_overrides {
      "tf.mydomain.com/mypackage" = "/path/to/your/.venv/bin"
  }
  
  direct {}
}
```

### Using the Provider

Now you can use your provider in Terraform by specifying it in the `provider` block in your `main.tf`.

```hcl
terraform {
  required_providers {
    myprovider = { source  = "tf.mydomain.com/mypackage"}
  }
}

provider "myprovider" {}

resource "myprovider_myresource" "myresource" {
  # ...
}
```

## Attributes

Attributes are the fields that an element exposes to the user to either set or read.
They take a name, a type, and a set of flags.

Attributes can be a combination of `required`, `computed`, and `optional`.
The values of these flags determine how the attribute is treated by TF and the framework.

| Required | Computed | Optional | Behavior                                                                                 |
|----------|----------|----------|------------------------------------------------------------------------------------------|
|          |          |          | _Invalid combination._ You must have at least one flag set.                              |
|          |          | X        | Fields may be set. TODO: Have default values.                                            |
|          | X        |          | Computed fields are read-only, value is set by the server and cannot be set by the user. |
|          | X        | X        | Field may be set. If not, uses value from server.                                        |
| X        |          |          | Required fields must be present in the configuration.                                    |
| X        |          | X        | _Invalid combination._                                                                   |
| X        | X        |          | _Invalid combination._                                                                   |
| X        | X        | X        | _Invalid combination._                                                                   |


## Types

This framework takes care to map Python types to TF types as closely as possible.
When you are writing element CRUD operations, you can consume and emit normal Python types
in the State dictionaries.

This framework handles the conversion to and from TF types and semantic equivalents.

| Python Type      | TF Type  | Framework Type    | Notes                                                     |
|------------------|----------|-------------------|-----------------------------------------------------------|
| `str`            | `string` | `String`          |                                                           |
| `int`, `float`   | `number` | `Number`          |                                                           |
| `bool`           | `bool`   | `Bool`            |                                                           |
| `Dict[str, Any]` | `string` | `NormalizedJson`  | Key order and whitespace are ignored for diff comparison. |

For `NormalizedJson` in particular, the framework will pass in `dict` and expect `dict` back.
That being said, if you are heavily editing a prettified JSON file and using that as
attribute input, you should wrap it in `jsonencode(jsondecode(file("myfile.json")))`
to allow Terraform to strip the file before it is passed to your provider.
Otherwise, the state will be ugly and will change every time you make whitespace
changes to the file.

## Errors

All errors are reporting using `Diagnostics`.
This parameter is passed into most operations, and you can
add warnings or errors.

Be aware: Operations that add error diagnostics will be considered
failed by Terraform.  Warnings are not, however.

You can add path information to your diagnostics.
This allows TF to display which specific field led to the error.
It's very helpful to the user.

## Examples

```python
from typing import Optional, Type
import hashlib

from tf import schema, types
from tf.schema import Attribute, Schema
from tf.iface import Config, DataSource, Resource, State, CreateContext, ReadContext, UpdateContext, DeleteContext
from tf.provider import Provider
from tf.runner import run_provider
from tf.utils import Diagnostics


class HasherProvider(Provider):
    def __init__(self):
        self.salt = b""

    def get_model_prefix(self) -> str:
        return "hasher_"

    def full_name(self) -> str:
        return "tf.example.com/hasher/hasher"

    def get_provider_schema(self, diags: Diagnostics) -> schema.Schema:
        return schema.Schema(
            version=1,
            attributes=[
                Attribute("salt", types.String(), required=True),
            ]
        )

    def validate_config(self, diags: Diagnostics, config: Config):
        if len(config["salt"]) < 8:
            diags.add_error("salt", "Salt must be at least 8 characters long")

    def configure_provider(self, diags: Diagnostics, config: Config):
        self.salt = config["salt"].encode()

    def get_data_sources(self) -> list[Type[DataSource]]:
        return []

    def get_resources(self) -> list[Type[Resource]]:
        return [Md5HashResource]


class Md5HashResource(Resource):
    def __init__(self, provider: HasherProvider):
        self.provider = provider
    
    @classmethod
    def get_name(cls) -> str:
        return "md5_hash"
    
    @classmethod
    def get_schema(cls) -> Schema:
        return Schema(
            attributes=[
                Attribute("input", types.String(), required=True),
                Attribute("output", types.String(), computed=True),
            ]
        )

    def create(self, ctx: CreateContext, planned_state: State) -> State:
        return {
            "input": planned_state["input"],
            "output": hashlib.md5(self.provider.salt + planned_state["input"].encode()).hexdigest()
        }

    def read(self, ctx: ReadContext, current_state: State) -> State:
        # Normally we would have to talk to a remove server, but this is local
        return {"input": current_state["input"], "output": current_state["output"]}

    def update(self, ctx: UpdateContext,  current_state: State, planned_state: State) -> State:
        return {
            "input": planned_state["input"],
            "output": hashlib.md5(self.provider.salt + planned_state["input"].encode()).hexdigest()
        }

    def delete(self, ctx: DeleteContext, current_state: State) -> Optional[State]:
        return None

if __name__ == "__main__":
    provider = HasherProvider()
    run_provider(provider)
```

Then we could consume this in Terraform like so:

```hcl
provider "hasher" {
  salt = "123456789"
}

resource "hasher_md5_hash" "myhash" {
  input = "hello"
}

output "hash" {
  value = hasher_md5_hash.myhash.output
}
```
