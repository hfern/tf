**********
Stable API
**********

.. py:module:: tf

Execution Interface
===================

The execution interface provides program entrypoints for OpenTofu to run your provider.


.. autofunction:: tf.runner.run_provider

An installation utility is provided to install your provider.

.. autofunction:: tf.runner.install_provider

You are expected to provide a `main.py` file in your provider package with a method
(set as an entrypoint)
that calls
:func:`~tf.runner.run_provider` and :func:`~tf.runner.install_provider`.

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

