**********
Stable API
**********

.. py:module:: tf

:code:`tf`'s API consists of:

* Low-level protocol classes that library consumers are expected to implement (such as :class:`~tf.iface.Provider`, :class:`~tf.iface.Resource`, and :class:`~tf.iface.DataSource`).
* Mid-level "glue" for schema definitions, such as :class:`~tf.schema.Attribute` and :class:`~tf.schema.Schema`.
* High-level commonly-used types such as :class:`~tf.types.String`, and :class:`~tf.types.List`.
* A handful of utility functions and classes, such as :func:`~tf.runner.run_provider` and :class:`~tf.runner.install_provider`.

As a library consumer and provider author, your primary interaction will be writing classes that satisfy :class:`~tf.iface.Provider`, :class:`~tf.iface.Resource`, and :class:`~tf.iface.DataSource`.
If your provider has a large number of elements, you will likely want to implement your own higher-level abstractions to stamp out boilerplate class definitions.
Protocols give you the flexibility to do this in a clean way.

However, it's perfectly fine (if somewhat tedious) to implement each element against it's protocol individually.

Execution Interface
===================

The execution interface provides program entrypoints for OpenTofu to run your provider.

You provider should have a `Console Script <https://setuptools.pypa.io/en/latest/userguide/entry_point.html#console-scripts>`_ entrypoint (named :code:`terraform-provider-myprovider`) pointing to your main function.
Your main function should create an instance of your provider and call :func:`~tf.runner.run_provider`.

.. autofunction:: tf.runner.run_provider

An installation utility is provided to install your provider into the plugins directory.

.. warning::
    Running :func:`~tf.runner.install_provider`. is only required if you want to install your provider *in development mode* into your plugin directory.
    There are easier ways to test your provider during development, such as setting the :code:`TF_CLI_CONFIG_FILE`.

.. autofunction:: tf.runner.install_provider


Provider Interface
==================

To implement a provider, you must subclass :class:`~tf.iface.Provider` and implement the methods.
Essentially a Provider answers some questions about itself, allows configuration of itself,
and provides a list of :class:`~tf.iface.DataSource` and :class:`~tf.iface.Resource` classes it supports.

.. autoclass:: tf.iface.Provider
   :members:

The :class:`~tf.iface.AbstractResource` represents an *element*: a data source or a resource.
Both types of elements must be named and have a schema.

.. autoclass:: tf.iface.AbstractResource
   :members:

Data Sources
------------

A DataSource is the simplest element to implement -- it's stateless and only provides data.
A DataSource must implement one method, :func:`~tf.iface.DataSource.read`,
and may optionally implement :func:`~tf.iface.DataSource.validate_config`.

.. autoclass:: tf.iface.DataSource
   :show-inheritance:
   :members:

Resources
---------

A Resource is a more complex element to implement -- it's stateful and provides data and actions.
You must implement:
:func:`~tf.iface.AbstractResource.get_name` and, :func:`~tf.iface.AbstractResource.get_schema`
as well as
:func:`~tf.iface.Resource.create`, :func:`~tf.iface.Resource.read`, :func:`~tf.iface.Resource.update`,
and :func:`~tf.iface.Resource.delete` to control the lifecycle of the resource.

You may also optionally implement :func:`~tf.iface.Resource.import_` and :func:`~tf.iface.Resource.plan`,
:func:`~tf.iface.Resource.upgrade`, and :func:`~tf.iface.Resource.validate` to further hook into the lifecycle.


.. autoclass:: tf.iface.Resource
   :show-inheritance:
   :members:


State
-----

*State* is a snapshot of your resource at a point in time.
It is a dictionary of field names to values.

.. autoclass:: tf.iface.State
   :members:


Config
------

*Config* is used instead of State during validation.

.. autoclass:: tf.iface.Config
   :members:

Schemas
============

Every resource must be specified with a schema.
A schema consists of a version, a set of fields, and a set of block types.

.. autoclass:: tf.schema.Schema
    :members:

Attributes
----------

An attribute is a field in a schema. It ties a field name to a type and a set of behaviors.

.. autoclass:: tf.schema.Attribute
    :members:

Blocks
------

Blocks are a way to group fields together in a schema. They are akin to sub-resources.
Blocks define their own attributes and may have nested blocks.

.. autoclass:: tf.schema.Block
    :members:

Types
-----

All types must implement the :class:`~tf.types.TfType` interface.

.. autoclass:: tf.types.TfType
    :members:

A handful of types are provided for you:

.. autoclass:: tf.types.Bool
.. autoclass:: tf.types.Number
.. autoclass:: tf.types.String
.. autoclass:: tf.types.List
.. autoclass:: tf.types.Set

Several utility types are also provided:

.. autoclass:: tf.types.NormalizedJson
   :show-inheritance:


Unknown
-------
:class:`~tf.types.Unknown` is a special `value` that represents a value that is not known at plan time.
Unknown is a fundamental part of TF's design and is used extensively in the planning phase.

TF makes a distinction between `null` and `unknown`. :code:`tf` represents them with :code:`None` and :code:`tf.types.Unknown` respectively.

.. autoclass:: tf.types.Unknown
   :members:
