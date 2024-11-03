from typing import Sequence

from tf.schema import Attribute
from tf.types import Unknown
from tf.utils import Diagnostics


def check_attributes(diags: Diagnostics, attributes: Sequence[Attribute]):
    for a in attributes:
        path = {"path": [a.name]}
        # False converts to None, so we drop Optional here and only deal with true/false
        # In the proto, there are no false values, only unset values.
        optional = a.optional or False
        required = a.required or False
        computed = a.computed or False

        # Optional
        if optional and required:
            diags.add_error("Optionality cannot be set if required", **path)

        if not optional and (not required and not computed):
            diags.add_error("Optionality must be set if required omitted and not computed", **path)

        # Required
        if required and optional:
            diags.add_error("Required cannot be set if optional", **path)

        if required and computed:
            diags.add_error("Required cannot be set if computed", **path)

        if not required and not optional and not computed:
            diags.add_error("Required must be set if optional omitted and not computed", **path)

        # Computed
        if computed and required:
            diags.add_error("Computed cannot be set if required", **path)

        if not computed and a.default is not Unknown:
            diags.add_error("You cannot set a default value if computed is not also set", **path)
