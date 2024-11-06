# Example

Here is a provider built using this framework that hashes a string using MD5.

While this provider does not talk to a remote server, it demonstrates how to use the framework to build a provider.


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