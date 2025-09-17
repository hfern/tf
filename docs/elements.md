# Element Schemas

The `tf` framework supports creating TF Protocol objects using Python classes.
`tf` managed converting these objects and types back and forth between Python and TF.

At a high level:

* An _Element_ is either a [`DataSource`](api.html#data-sources) or a [`Resource`](api.html#resources).
* An _Element_ has a _Schema_ that defines the attributes and blocks that it exposes to the user.
* An _Attribute_ is a field name, a Type, and a set of behaviors.
* A _Type_ is a Python class that can convert between Python and TF representations of the underlying data type.

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

You can implement your own type through [`TfType`](api.html#tf.types.TfType).

## Attributes

Attributes are the fields that an element exposes to the user to either set or read.
They take a name, a type, and a set of flags.

```python
from tf import schema, types

attribute = schema.Attribute("a", types.Number(), required=True)
```

### Behaviors

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



## Schema

Both the `Resource` and `DataSource` elements are defined by a schema.

A schema is a versioned collection of attributes and blocks that the element exposes to the user.


## Errors

All errors are reported using `Diagnostics`.
This parameter is passed into most operations, and you can
add warnings or errors.

Be aware: Operations that add error diagnostics will be considered
failed by Terraform.  Warnings are not, however.


You may optionally add path information to your diagnostics.
This allows TF to display which specific field led to the error.
It's very helpful to the user.

.. literalinclude:: examples/datasource-dns.py
