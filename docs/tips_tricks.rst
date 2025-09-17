***************
Tips and Tricks
***************

Using a Debugger
================

To use a debugger, you must pre-emptively launch your provider in long-lived server mode by running ``terraform-provider-$providername --stable --dev`` in a terminal.
This will start the provider, dump an ``export TF_REATTACH_PROVIDERS=...`` command, and wait for connections.

In another terminal, you can paste and execute the ``export TF_REATTACH_PROVIDERS=...`` command to set up your environment.
Then you can run ``tofu plan`` or ``terraform apply`` as usual.

Tofu will connect to the already-running provider instead of starting it on-demand.
By launching your provider with ``--stable --dev`` in your debugger, you can set breakpoints and inspect state as needed.


Building a Binary
==================

Ultimately, if you want to distribute your provider you'll need to build a single standalone binary.
The Terraform registry (and all custom provider registries) expect a binary executable, not a Python script.

There are many ways to build a binary from Python code, but the easiest one to get working is `pex <https://docs.pex-tool.org/>`_.

Pex essentially bundles up your Python code and all its dependencies into a single file that can be executed as a binary.
When the binary is run, it sets up a virtual environment and runs your code in that environment.

Another nice feature of pex is that it can generate binaries for multiple platforms (Linux, Windows, MacOS) from a single machine.

We have had success building provider binaries with Pex and uploading and consuming them from Terraform private registries.
From tofu and the registry's perspective, the pex binary no different than a Go binary built using the official Terraform provider framework.

The provider upload registry APIs are not standardized across hosting providers, so you'll need to explore bundling and uploading the binaries yourself for your choice of registry.

Roughly, the steps to build a pex binary are:

#. Install pex: ``pip install pex``, preferably into a separate virtual environment or as a development dependency of your provider project.
#. Dump the dependencies of your provider into a requirements file:

   .. code-block:: shell

      pip freeze > requirements.txt

   Alternatively, you can use a package-manager specific command
   such as ``uv export -f requirements.txt > requirements.txt``).

#. Build the pex binary:

   .. code-block:: shell

      pex -r requirements.txt ./ \
        -o terraform-provider-$providername \
        --scie eager \
        -m providerpackage.main:main

   By using ``--scie eager``, pex will include a Python interpreter in the binary as well as all the dependencies.
   This means everything needs to run the provider is contained in the single binary file.

You will now have a binary executable named ``terraform-provider-$providername`` that you can upload to your registry and use with Terraform.

At this point you have a minimum viable provider binary, but you will need to think about multiple platforms and architectures and ABIs.
