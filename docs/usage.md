# Using the Framework

There are four primary interfaces in this framework:

1. **Provider** - By implementing this interface, you can define
    a new provider. This defines its own schema, and supplies
    resource, data source, and function classes to the framework.
1. **Data Source** - This interface is used to define a data source, which
    is a read-only object that can be used to query information
    from the provider or backing service.
1. **Resource** - This interface is used to define a resource, which
    is a read-write object that can be used to create, update,
    and delete resources in the provider or backing service.
    Resources represent full "ownership" of the underlying object.
    This is the primary type you will use to interact with the system.
1. **Function** - This interface is used to define provider functions, which
    are stateless operations that can transform data, perform calculations,
    or validate inputs. Functions are called directly from Terraform
    configurations and return a single value.

To use this interface, create one class implementing `Provider`, and any number
of classes implementing `Resource`, `DataSource`, and `Function`.

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

## Entry Point Name

TF requires a specific naming convention for the provider. Your executable
must be named in the form of `terraform-provider-<providername>`.
This means that you must your [entrypoint](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
similarly.

```toml
[project.scripts]
terraform-provider-myprovider = "mypackage.main:main"
```

## TF Developer Overrides

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

## Using the Provider

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

# Using provider functions
output "example" {
  value = provider::myprovider::myfunction("input")
}
```

For more details on implementing functions, see the [Functions documentation](functions.md).
