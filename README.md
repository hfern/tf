# Python TF Plugin Framework

This package acts as an interface for writing a Terraform/OpenTofu ("TF")
provider in Python.
This package frees you of the toil of interfacing with the TF type system,
implementing the Go Plugin Protocol, implementing the TF Plugin Protocol, and
unbundling compound API calls.

Instead, you can simply implement Create, Read, Update, and Delete operations
using idiomatic Python for each of the resource types you want to support.

* **Documentation** is available at [https://python-tf.readthedocs.io](https://python-tf.readthedocs.io)
* **Source Code** is available at [https://github.com/hfern/tf](https://github.com/hfern/tf)

## Installation

This package is available on PyPI, and can be installed using pip.

```bash
pip install tf
```
