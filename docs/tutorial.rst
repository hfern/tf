********
Tutorial
********

In this tutorial, we'll walk through using ``tf`` to create a simple math provider.

We'll use ``uv``, a popular package manager.

Project Setup
=============

We're going to name our provider Python package ``mathprovider``. We'll create a directory for it right in our home directory -- ``mkdir ~/mathprovider && cd ~/mathprovider``.
From now on, we'll assume you're in that directory.

First, let's start a package with ``uv``:

.. code-block:: shell

    $ uv init --package
        Initialized project `mathprovider`

This will give us a couple of files we can work with, namely ``pyproject.toml`` and the ``src/`` directory.

Let's add ``tf`` as a dependency.

.. code-block:: shell

    $ uv add tf
        Resolved 8 packages in 114ms
              Built mathprovider @ file://~/mathprovider
        Prepared 1 package in 4ms
        Installed 8 packages in 2ms
         + cffi==1.17.1
         + cryptography==45.0.6
         + grpcio==1.74.0
         + mathprovider==0.1.0 (from file://~/mathprovider)
         + msgpack==1.1.1
         + protobuf==5.29.5
         + pycparser==2.22
         + tf==1.1.0


Finally, we're going to have a main function in our package that needs to be the entrypoint.
We'll create a  ``src/mathprovider/main.py`` file and a ``main`` function in it.

.. code-block:: python
    :caption: src/mathprovider/main.py

    import sys
    from tf.runner import run_provider

    def main():
        provider = None
        run_provider(provider, sys.argv)


Let's create a console script in ``pyproject.toml`` that points to our main function.
These need to have a specific name (``terraform-provider-<PROVIDER_NAME>``).
We add this to a new ``[project.scripts]`` section of ``pyproject.toml``.

.. code-block:: toml
    :caption: pyproject.toml

    ...

    [project.scripts]
    terraform-provider-math = "mathprovider.main:main"

Finally, we have ``uv`` create this for us with ``uv sync``.

You will now find a ``.venv/`` directory in your project along with a ``.venv/bin/terraform-provider-math`` script.

If we run it, we'll find a bunch of garbage output and our program hanging:

.. code-block:: shell

    $ uv run terraform-provider-math
        1|6|unix|/tmp/tmp5hf5fmoy/py-tf-plugin.sock|grpc|XXX...
        (hang)

What's going on here? Our provider entrypoint is speaking the Go Plugin Protocol, and it's waiting for Terraform to connect to it.

Let's ``ctrl-c`` out of it.
We now have the basic scaffolding of a provider, but it doesn't do anything yet.

Creating the Provider
=======================

Let's sketch out the basic provider class in our ``main.py``.

First, for simplicity let's import everything we'll need later.

.. code-block:: python
    :caption: src/mathprovider/main.py

    import sys
    from typing import Optional, Type

    from tf import runner
    from tf import types as t
    from tf.iface import (
        Config,
        DataSource,
        ReadDataContext,
        Resource,
        State,
    )
    from tf.provider import Diagnostics, Provider
    from tf.schema import Attribute, Schema

Now, we can add our ``MathProvider`` class that implements the ``Provider`` protocol.

.. code-block:: python
    :caption: src/mathprovider/main.py

    class MathProvider(Provider):
        def get_model_prefix(self) -> str:
            return "math_"

        def get_provider_schema(self, diags: Diagnostics) -> Schema:
            return Schema(attributes=[])

        def full_name(self) -> str:
            return "test.terraform.io/test/math"

        def validate_config(self, diags: Diagnostics, config: Config):
            pass

        def configure_provider(self, diags: Diagnostics, config: Config):
            pass

        def get_data_sources(self) -> list[Type[DataSource]]:
            return []

        def get_resources(self) -> list[Type[Resource]]:
            return []

While we'll leave most of these empty for now, there are a few ones worth noting:

- ``get_model_prefix`` returns a prefix that will be used for all attributes in this provider.
  Tofu decides which resources map to which provider by using their type name prefix.
  We'll use ``math_`` here, so our resources will be named similarly to ```math_divider``.

- ``full_name`` returns the full name of the provider, which is used in Tofu configuration files.
  This should be in the format ``<NAMESPACE>/<PROVIDER_NAME>``.
  If you ever upload your provider to the Terraform Registry, this should match the name you use there.
  That provider name following the last slash should align with the model prefix (e.g. ``math`` and ``math_``).

- ``get_data_sources`` and ``get_resources`` return lists of data source and resource classes that this provider implements.
  We'll leave these empty for now, but we'll add to them later.

Finally, we need to plug this provider class into our ``main`` function.
We can do that by instantiating it and passing it to ``run_provider``.

.. code-block:: python
    :caption: src/mathprovider/main.py

    def main():
        provider = MathProvider()
        runner.run_provider(provider, sys.argv)

Tofu Environment
=================

To easily get started using our provider, we're going to create an example directory
for our ``.tf`` files and a ``tofu.rc`` file

Let's create a ``example/`` directory in our project root and ``tofu.rc`` and ``main.tf`` files in it.

.. code-block:: shell

    $ mkdir example && cd example
    $ touch tofu.rc main.tf

The ``tofu.rc`` file is a configuration file for Tofu itself.
As we are developing our provider, we want Tofu to find it in our project's virtual environment's ``bin`` directory.

Uv has helpfully created a ``.venv/`` directory in our project root. The ``tofu.rc`` file needs to point to the absolute path of our ``.venv/bin`` directory.
You'll need to change ``/home/hunter/mathprovider`` to the absolute path of your own project directory.

.. code-block:: hcl
    :caption: example/tofu.rc

    provider_installation {
      dev_overrides {
          "test.terraform.io/test/math" = "/home/hunter/mathprovider/.venv/bin"
      }
      direct {}
    }

Let's also fill in our ``main.tf`` file to use our provider.
Right now we'll just specify the provider and configure it with no arguments.

.. code-block:: hcl
    :caption: example/main.tf

    terraform {
      required_providers {
        math = {
          source  = "test.terraform.io/test/math"
        }
      }
    }

    provider "math" {}

Finally, in our shell we'll need to have tofu use our custom ``tofu.rc`` file.
We can do this by setting the ``TF_CLI_CONFIG_FILE`` environment variable to point to our ``tofu.rc`` file.

.. code-block:: shell

    $ export TF_CLI_CONFIG_FILE=/home/hunter/mathprovider/example/tofu.rc

Now we can run ```tofu plan`` while we are in the ``example/`` directory. Our ``main.tf`` isn't doing much yet, but we should see our provider being started up.

.. code-block:: shell

    $ tofu plan
        │ Warning: Provider development overrides are in effect
        │
        │ The following provider development overrides are set in the CLI configuration:
        │  - test.terraform.io/test/math in /home/hunter/mathprovider/.venv/bin
        │
        │ The behavior may therefore not match any released version of the provider and applying changes may cause the state to become
        │ incompatible with published releases.
        ╵

        No changes. Your infrastructure matches the configuration.

        OpenTofu has compared your real infrastructure against your configuration and found no differences, so no changes are needed.


Adding a Data Source
======================

In this tutorial we'll only implement a single data source, ``math_divider``, which will take two numbers and return their quotient.

Let's add another class to our ``main.py`` file that implements the ``DataSource`` protocol.
We'll also add some basic validation to ensure the divisor is not zero.

.. code-block:: python
    :caption: src/mathprovider/main.py

    class Divider(DataSource):
        @classmethod
        def get_name(cls) -> str:
            return "divider"

        @classmethod
        def get_schema(cls) -> Schema:
            return Schema(
                attributes=[
                    Attribute("dividend", t.Number(), required=True),
                    Attribute("divisor", t.Number(), required=True),
                    Attribute("quotient", t.Number(), computed=True),
                ]
            )

        def validate(self, diags: Diagnostics, type_name: str, config: Config):
            super().validate(diags, type_name, config)
            if config["divisor"] == 0:
                diags.add_error(
                    "Invalid divisor",
                    "The 'divisor' attribute cannot be zero.",
                )

        def read(self, ctx: ReadDataContext, config: Config) -> Optional[State]:
            return {
                "dividend": config["dividend"],
                "divisor": config["divisor"],
                "quotient": config["dividend"] / config["divisor"],
            }

        def __init__(self, provider):
            pass

Then we need to add this class to our provider's ``get_data_sources`` method.

.. code-block:: python
    :caption: src/mathprovider/main.py

     ...

     class MathProvider:
        ...

        def get_data_sources(self) -> list[Type[DataSource]]:
            return [Divider]

Finally, let's use our new data source in our ``main.tf`` file.
We'll add an ``output`` block so we can see the result of our division.

.. code-block:: hcl
    :caption: example/main.tf

    terraform {
      required_providers {
        math = {
          source  = "test.terraform.io/test/math"
        }
      }
    }

    provider "math" {}

    data "math_divider" "example" {
      dividend = 10
      divisor  = 2
    }

    output "result" {
      value = data.math_divider.example.quotient
    }

Now if we run ``tofu plan`` again, we should see our data source being read and the output being computed.

.. code-block:: shell

    $ tofu plan
        │ Warning: Provider development overrides are in effect
        │
        │ The following provider development overrides are set in the CLI configuration:
        │  - test.terraform.io/test/math in /home/hunter/mathprovider/.venv/bin
        │
        │ The behavior may therefore not match any released version of the provider and applying changes may cause the state to become
        │ incompatible with published releases.
        ╵
        data.math_divider.example: Reading...
        data.math_divider.example: Read complete after 0s

        Changes to Outputs:
          + result = 5

        You can apply this plan to save these new output values to the OpenTofu state, without changing any real infrastructure.

        ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

        Note: You didn't use the -out option to save this plan, so OpenTofu can't guarantee to take exactly these actions if you run
        "tofu apply" now.

Congratulations! You've created a simple Tofu provider with a data source!
Now you can experiment with adding more data sources and resources to your provider.
