from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, Type, TypeAlias

from tf.schema import Attribute, NestedBlock, Schema
from tf.utils import Diagnostics

"""
State is the current state of a resource.
It is a dictionary where field names are mapped to Python values (or None, or Unknown).
Resource operations are mostly just pushing around, mutating, and returning State.
"""
State: TypeAlias = dict


"""
Config is like State, except its used in configuration validation and the values are null when
they are not bound to a value.
This is because the configuration is not yet bound to a resource.
This is merely for validating that set of input parameters or values are correct.
"""
Config: TypeAlias = dict


class AbstractResource(Protocol):
    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        """Get the type name for this resource type"""

    @classmethod
    @abstractmethod
    def get_schema(cls) -> Schema:
        """Get the schema for this resource"""


@dataclass
class _Context:
    diagnostics: Diagnostics
    type_name: str


class ReadDataContext(_Context): ...


def _validate_config(
    diags: Diagnostics, type_name: str, config: Config, attributes: Sequence[Attribute], blocks: Sequence[NestedBlock]
):
    """Validate the configuration"""
    # Verify each supplied field is valid
    attr_names = {a.name for a in attributes}
    block_names = {b.type_name for b in blocks}
    known_keys = attr_names | block_names
    unknown_keys = set(config.keys()) - known_keys

    # Kind of lazy about this right now... might need schema version promotion logic later
    for k in unknown_keys:
        diags.add_error(
            f"Unknown field {type_name}.{k}",
            f"The field '{k}' was supplied, but is not a valid field for {type_name}."
            f" This is likely a bug in your state file."
            f" If you did not manually edit state, please report this to your provider.",
        )

    if len(unknown_keys) > 0:
        return

    amap = {a.name: a for a in attributes}

    for k in attr_names:
        if k not in config:
            # If the field is not set, we don't need to validate it -- makes unit tests easy
            continue

        v = config[k]
        a = amap[k]
        if v is not None and a.computed and not a.optional and not a.required:
            diags.add_error(
                f"Field {type_name}.{k} is read-only and should not be set",
                path=[k],
            )


class DataSource(AbstractResource, Protocol):
    def validate(self, diags: Diagnostics, type_name: str, config: Config):
        """Validate the data source configuration"""
        schema = self.get_schema()
        _validate_config(diags, type_name, config, schema.attributes, schema.block_types)

    @abstractmethod
    def read(self, ctx: ReadDataContext, config: Config) -> Optional[State]:
        """Read the data source"""


# Right now all the same but UpdateContext should have a planning/delta fields method
class CreateContext(_Context): ...


class ReadContext(_Context): ...


class UpdateContext(_Context): ...


class DeleteContext(_Context): ...


class UpgradeContext(_Context): ...


class ImportContext(_Context): ...


@dataclass
class PlanContext(_Context):
    changed_fields: set[str]


class Resource(AbstractResource, Protocol):
    def validate(self, diags: Diagnostics, type_name: str, config: Config):
        """
        Validate the resource configuration

        This is called before any other operation to validate the configuration of the resource.
        You should run parameter validation here.
        Generate errors and warnings through the `diags` object.

        :param diags: Diagnostics
        :param type_name: The type name of the resource
        :param config: The configuration to validate
        """
        schema = self.get_schema()
        _validate_config(diags, type_name, config, schema.attributes, schema.block_types)

    @abstractmethod
    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        """
        Create the resource, returning the actual state after creation.

        This is called when a user runs `opentofu apply` and the resource needs to be initially created.

        :param ctx: CreateContext
        :param planned: The planned state of the resource
        """

    @abstractmethod
    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        """Read the current state of the resource"""

    @abstractmethod
    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        """Update the resource to the planned state, returning the actual state after the update"""

    @abstractmethod
    def delete(self, ctx: DeleteContext, current: State):
        """Delete the resource, returning None generally"""

    def plan(self, ctx: PlanContext, current: Optional[State], planned: State) -> Optional[State]:
        """Modify the resource change plan"""
        return planned

    def import_(self, ctx: ImportContext, id: str) -> Optional[State]:
        """
        Import a resource

        This is called when a user runs `opentofu import` and provides a resource ID to import.

        :param ctx: ImportContext
        :param id: The resource ID to import
        """

    # TODO(Hunter): move

    def upgrade(self, ctx: UpgradeContext, version: int, old: State) -> Optional[State]:
        """Upgrade an old resource state to the newest schema version"""
        ctx.diagnostics.add_warning(f"Using default upgrade for {ctx.type_name}.")
        # TODO(Hunter): This should probably iterate all attrs, find ones not in the old state, and set defaults
        return old


def is_importable(klass: Type[Resource]) -> bool:
    """Has the resource implemented the import_ method"""
    return hasattr(klass, "import_") and klass.import_ is not Resource.import_


class Provider(Protocol):
    @abstractmethod
    def get_model_prefix(self) -> str:
        """Get the model prefix for all loaded resources"""

    @abstractmethod
    def get_provider_schema(self, diags: Diagnostics) -> Schema:
        """Get the schema for the provider"""

    @abstractmethod
    def full_name(self) -> str:
        """Get the full provider name eg `terraform.example.com/ex/ex`"""

    @abstractmethod
    def validate_config(self, diags: Diagnostics, config: Config):
        """Validate the provider configuration"""

    @abstractmethod
    def configure_provider(self, diags: Diagnostics, config: Config):
        """Called when the provider is configured. This is a good place to set up any global state"""

    @abstractmethod
    def get_data_sources(self) -> list[Type[DataSource]]:
        """Get all the data source types that this provider supports"""

    @abstractmethod
    def get_resources(self) -> list[Type[Resource]]:
        """Get all the resource types that this provider supports"""

    def new_resource(self, klass: Type[Resource]) -> Resource:
        return klass(self)  # pyre-ignore[19]: noqa: Don't care about __init__

    def new_data_source(self, klass: Type[DataSource]) -> DataSource:
        return klass(self)  # pyre-ignore[19]: noqa: Don't care about __init__
