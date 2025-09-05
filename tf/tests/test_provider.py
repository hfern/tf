import copy
import json
from io import StringIO
from typing import Optional, Type
from unittest import TestCase, mock
from unittest.mock import Mock, patch

import grpc
import msgpack

from tf import blocks, schema, types
from tf import provider as p
from tf.gen import tfplugin_pb2 as pb
from tf.iface import (
    Config,
    CreateContext,
    DeleteContext,
    ImportContext,
    ReadContext,
    ReadDataContext,
    State,
    UpdateContext,
)
from tf.provider import DataSource, Diagnostics, Resource
from tf.types import Unknown
from tf.utils import read_dynamic_value, to_dynamic_value


class ExampleProvider(p.Provider):
    def full_name(self) -> str:
        return "tf.example.com/example/example"

    def __init__(self):
        self.validated = False
        self.configured = False

    def get_model_prefix(self) -> str:
        return "test_"

    def get_provider_schema(self, diags: Diagnostics) -> schema.Schema:
        return schema.Schema(
            attributes=[
                schema.Attribute("provider1", types.String(), optional=True),
            ],
        )

    def validate_config(self, diags: Diagnostics, config: Config):
        if config.get("provider1") == "reject":
            diags.add_error("Rejected!")
            return

        self.validated = True

    def configure_provider(self, diags: Diagnostics, config: Config):
        self.configured = True

    def get_data_sources(self) -> list[Type[DataSource]]:
        return [FavoriteNumberDataSource, FavoriteNumberErrorsDataSource]

    def get_resources(self) -> list[Type[Resource]]:
        return [ExampleMathResource, ErrorsAlotResource, JsonResource, ComplexResource]


class ExampleMathResource(p.Resource):
    @classmethod
    def get_name(cls) -> str:
        return "math"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("a", types.Number(), required=True),
                schema.Attribute("b", types.Number(), required=True, requires_replace=True),
                schema.Attribute("sum", types.Number(), computed=True),
                schema.Attribute("product", types.Number(), computed=True),
            ],
        )

    def __init__(self, provider: ExampleProvider):
        self.provider = provider

    @classmethod
    def mock_create(cls, ctx: CreateContext, planned: State) -> Optional[State]:
        return None

    @classmethod
    def mock_read(cls, ctx: ReadContext, current: State) -> Optional[State]:
        return

    @classmethod
    def mock_update(cls, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        return

    @classmethod
    def mock_delete(cls, ctx: DeleteContext, current: State) -> Optional[State]:
        return

    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        self.mock_create(ctx, planned)
        planned["sum"] = planned["a"] + planned["b"]
        planned["product"] = planned["a"] * planned["b"]
        return planned

    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        self.mock_read(ctx, current)
        return current

    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        self.mock_update(ctx, current, planned)
        if planned["a"] + planned["b"] == 0:
            ctx.diagnostics.add_error("Can't sum to zero!")
            return None

        planned = copy.deepcopy(planned)
        planned["sum"] = planned["a"] + planned["b"]
        planned["product"] = planned["a"] * planned["b"]
        return planned

    def delete(self, ctx: DeleteContext, current: State):
        self.mock_delete(ctx, current)
        pass


class ErrorsAlotResource(ExampleMathResource):
    @classmethod
    def get_name(cls) -> str:
        return "errorsalot"

    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        ctx.diagnostics.add_error("Create failed")
        return {}

    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        ctx.diagnostics.add_error("Read failed")
        return

    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        ctx.diagnostics.add_error("Update failed")
        return

    def delete(self, ctx: DeleteContext, current: State):
        ctx.diagnostics.add_error("Delete failed")
        return

    def validate(self, diags: Diagnostics, type_name: str, config: Config):
        diags.add_error("Validate failed")


class JsonResource(p.Resource):
    @classmethod
    def get_name(cls) -> str:
        return "json"

    def __init__(self, _):
        pass

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            attributes=[
                schema.Attribute("json", types.NormalizedJson(), required=True),
            ],
        )

    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        return planned

    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        return current

    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        return planned

    def delete(self, ctx: DeleteContext, current: State):
        return


class CustomTypeStrictSet(types.Set):
    """A type of set for testing that will fail if Unknown is passed to semantically_equal"""

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        self.on_check_semantic_equality(a_decoded, b_decoded)

        if a_decoded is Unknown or b_decoded is Unknown:
            raise ValueError("Wow this should never have been called!!")

        return super().semantically_equal(a_decoded, b_decoded)

    @classmethod
    def on_check_semantic_equality(cls, a, b):
        pass


class ComplexResource(p.Resource):
    """A resource with a set attribute: a complex type that requires special handling"""

    @classmethod
    def get_name(cls) -> str:
        return "complex"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("favorite_numbers", CustomTypeStrictSet(types.Number()), computed=True),
            ],
        )

    def __init__(self, *args):
        pass

    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        return {
            "favorite_numbers": [9, 8, 7],
        }

    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        return {
            "favorite_numbers": [9, 8, 7],
        }

    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        return {"favorite_numbers": list(reversed(planned["favorite_numbers"]))}  # sets can be any order :)

    def delete(self, ctx: DeleteContext, current: State):
        return None


class FavoriteNumberDataSource(p.DataSource):
    @classmethod
    def get_name(cls) -> str:
        return "favorite_number"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            attributes=[
                schema.Attribute("number", types.Number(), computed=True),
            ],
        )

    def __init__(self, *args):
        pass

    def read(self, ctx: ReadDataContext, config: Config) -> Optional[State]:
        return {"number": 42}


class FavoriteNumberErrorsDataSource(FavoriteNumberDataSource):
    @classmethod
    def get_name(cls) -> str:
        return "favorite_number_errors"

    def read(self, ctx: ReadDataContext, config: Config) -> Optional[State]:
        ctx.diagnostics.add_error("Read failed")
        return

    def validate(self, diags: Diagnostics, type_name: str, config: Config):
        diags.add_error("Validate failed")


class ExampleImportingProvider(ExampleProvider):
    """A Provider with a resource that implements import"""

    def get_data_sources(self) -> list[Type[DataSource]]:
        return []

    def get_resources(self) -> list[Type[Resource]]:
        return [ImportableMathResource]


class ImportableMathResource(ExampleMathResource):
    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("you_imported", types.String(), computed=True),
                schema.Attribute("some_json", types.NormalizedJson(), computed=True),
            ],
        )

    def import_(self, ctx: ImportContext, id: str) -> Optional[State]:
        return {"you_imported": id, "some_json": {"wow": {"thats": ["a", "lot", "of", "json", 5]}}}


class ComplexBlocksProvider(ExampleProvider):
    """A Provider with complex block types"""

    def get_data_sources(self) -> list[Type[DataSource]]:
        return []

    def get_resources(self) -> list[Type[Resource]]:
        return [HasSetBlockResource]


class HasSetBlockResource(ExampleMathResource):
    @classmethod
    def get_name(cls) -> str:
        return "has_set_block"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[],
            block_types=[
                blocks.SetNestedBlock(
                    "set_block",
                    schema.Block(
                        [
                            schema.Attribute("name", types.String(), required=True),
                            schema.Attribute("value", types.Number(), required=True),
                        ]
                    ),
                ),
            ],
        )

    def create(self, ctx: CreateContext, planned: State) -> Optional[State]:
        self.mock_create(ctx, planned)
        return planned

    @classmethod
    def mock_create(cls, ctx: CreateContext, planned: State) -> Optional[State]:
        """mock target"""

    def read(self, ctx: ReadContext, current: State) -> Optional[State]:
        # Oops -- this resource just drifts
        # This would lead to an inconsistency error in real TF
        for set_block in current.get("set_block", []):
            set_block["value"] += 1
            break  # only drift the first element

        return current

    def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
        # Check that the set logic works and that the changed order of the elements doesn't matter
        return {**planned, **{"set_block": list(reversed(planned["set_block"]))}}

    def delete(self, ctx: DeleteContext, current: State):
        return None


class DefaultAttributeProvider(ExampleProvider):
    def get_resources(self) -> list[Type[Resource]]:
        return [DefaultAttributeResource, OptionalAttributeWithoutDefaultResource]


class DefaultAttributeResource(ExampleMathResource):
    @classmethod
    def get_name(cls) -> str:
        return "math_with_default"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("a", types.Number(), required=True),
                schema.Attribute("b", types.Number(), required=True, requires_replace=True),
                schema.Attribute("c_with_default", types.Number(), computed=True, default=9001),
                schema.Attribute("sum", types.Number(), computed=True),
                schema.Attribute("product", types.Number(), computed=True),
            ],
        )


class OptionalAttributeWithoutDefaultResource(ExampleMathResource):
    @classmethod
    def get_name(cls) -> str:
        return "math_without_default"

    @classmethod
    def get_schema(cls) -> schema.Schema:
        return schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("a", types.Number(), required=True),
                schema.Attribute("b", types.Number(), required=True, requires_replace=True),
                schema.Attribute("c_without_default", types.Number(), optional=True),
                schema.Attribute("sum", types.Number(), computed=True),
                schema.Attribute("product", types.Number(), computed=True),
            ],
        )


class AbortError(Exception):
    def __init__(self, code, details):
        self.code = code
        self.details = details


class ServicerContextMock(grpc.ServicerContext):
    def __init__(self, metadata=None):
        self.metadata = metadata
        self.code = None
        self.details = None

    def invocation_metadata(self):
        return self.metadata

    def peer(self):
        return "the-peer"

    def peer_identities(self):
        return None

    def peer_identity_key(self):
        return None

    def auth_context(self):
        return None

    def send_initial_metadata(self, initial_metadata):
        return None

    def set_trailing_metadata(self, trailing_metadata):
        return None

    def abort(self, code, details):
        self.set_code(code)
        self.set_details(details)
        raise AbortError(code, details)

    def abort_with_status(self, status):
        self.set_code(status.code)
        raise AbortError(status.code, status.details)

    def set_code(self, code):
        self.code = code

    def set_details(self, details):
        self.details = details

    def is_active(self):
        return True

    def time_remaining(self):
        return 999999.0

    def cancel(self):
        raise NotImplementedError()  # ???

    def add_callback(self, callback):
        raise NotImplementedError()  # ???


class ProviderTestBase(TestCase):
    def setUp(self):
        super().setUp()

        self.res_create = self.patch_object(ExampleMathResource, "mock_create")
        self.res_read = self.patch_object(ExampleMathResource, "mock_read")
        self.res_update = self.patch_object(ExampleMathResource, "mock_update")
        self.res_delete = self.patch_object(ExampleMathResource, "mock_delete")

    def patch_object(self, *args, **kwargs):
        patch = mock.patch.object(*args, **kwargs)
        self.addCleanup(patch.stop)
        return patch.start()

    def provider_servicer_context(self, pclass=ExampleProvider):
        provider = pclass()
        servicer = p.ProviderServicer(provider)
        ctx = ServicerContextMock()
        return provider, servicer, ctx

    def assert_no_diagnostic_errors(self, resp):
        if resp.diagnostics is None:
            return

        self.assertEqual(resp.diagnostics, [])


class ProviderCacheTest(ProviderTestBase):
    # Caching/test coverage test

    def test_resource_cache(self):
        provider, servicer, ctx = self.provider_servicer_context()
        self.assertIs(
            servicer._get_res_attrs("test_math"),
            servicer._get_res_attrs("test_math"),
        )

    def test_blocks_cache(self):
        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)
        self.assertIs(
            servicer._get_res_blocks("test_has_set_block"),
            servicer._get_res_blocks("test_has_set_block"),
        )


class GetProviderSchemaTest(ProviderTestBase):
    def test_provider_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        md = dict(description_kind=pb.MARKDOWN)

        resp = servicer.GetProviderSchema(pb.GetProviderSchema.Request(), ctx)
        self.assertIsInstance(resp, pb.GetProviderSchema.Response)
        self.assert_no_diagnostic_errors(resp)

        self.assertEqual(
            resp.provider,
            pb.Schema(
                block=pb.Schema.Block(
                    attributes=[
                        pb.Schema.Attribute(name="provider1", type=b'"string"', optional=True, **md),
                    ]
                ),
            ),
        )

        self.assertEqual(
            resp.resource_schemas,
            {
                "test_math": pb.Schema(
                    version=2,
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="a", type=b'"number"', required=True, **md),
                            pb.Schema.Attribute(name="b", type=b'"number"', required=True, **md),
                            pb.Schema.Attribute(name="sum", type=b'"number"', computed=True, **md),
                            pb.Schema.Attribute(name="product", type=b'"number"', computed=True, **md),
                        ]
                    ),
                ),
                "test_errorsalot": pb.Schema(
                    version=2,
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="a", type=b'"number"', required=True, **md),
                            pb.Schema.Attribute(name="b", type=b'"number"', required=True, **md),
                            pb.Schema.Attribute(name="sum", type=b'"number"', computed=True, **md),
                            pb.Schema.Attribute(name="product", type=b'"number"', computed=True, **md),
                        ]
                    ),
                ),
                "test_json": pb.Schema(
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="json", type=b'"string"', required=True, **md),
                        ]
                    ),
                ),
                "test_complex": pb.Schema(
                    version=2,
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="favorite_numbers", type=b'["set","number"]', computed=True, **md),
                        ]
                    ),
                ),
            },
        )

        self.assertEqual(
            resp.data_source_schemas,
            {
                "test_favorite_number": pb.Schema(
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="number", type=b'"number"', computed=True, **md),
                        ]
                    ),
                ),
                "test_favorite_number_errors": pb.Schema(
                    block=pb.Schema.Block(
                        attributes=[
                            pb.Schema.Attribute(name="number", type=b'"number"', computed=True, **md),
                        ]
                    ),
                ),
            },
        )

        # provider_meta should now be set with an empty schema
        self.assertTrue(resp.HasField("provider_meta"))
        # It should have an empty block with no attributes
        self.assertEqual(resp.provider_meta.version, 0)
        self.assertTrue(resp.provider_meta.HasField("block"))
        self.assertEqual(len(resp.provider_meta.block.attributes), 0)
        self.assertEqual(len(resp.provider_meta.block.block_types), 0)
        self.assertEqual(resp.server_capabilities, pb.ServerCapabilities())
        self.assertEqual(resp.functions, {})

    def test_schema_caching(self):
        """Test that schemas are cached on subsequent calls"""
        provider, servicer, ctx = self.provider_servicer_context()

        # First call - schemas will be computed and cached
        resp1 = servicer.GetProviderSchema(pb.GetProviderSchema.Request(), ctx)
        self.assert_no_diagnostic_errors(resp1)

        # Second call - should use cached schemas
        resp2 = servicer.GetProviderSchema(pb.GetProviderSchema.Request(), ctx)
        self.assert_no_diagnostic_errors(resp2)

        # Responses should be identical
        self.assertEqual(resp1.resource_schemas, resp2.resource_schemas)
        self.assertEqual(resp1.data_source_schemas, resp2.data_source_schemas)


class ValidateProviderConfigTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateProviderConfig(
            pb.ValidateProviderConfig.Request(
                config=to_dynamic_value({"provider1": "ok"}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateProviderConfig.Response)
        self.assert_no_diagnostic_errors(resp)

    def test_errors(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateProviderConfig(
            pb.ValidateProviderConfig.Request(
                config=to_dynamic_value({"provider1": "reject"}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateProviderConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Rejected!",
                )
            ],
        )


class ConfigureProviderTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ConfigureProvider(
            pb.ConfigureProvider.Request(
                config=to_dynamic_value({"provider1": "ok"}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ConfigureProvider.Response)
        self.assert_no_diagnostic_errors(resp)
        self.assertTrue(provider.configured)


class PlanResourceChangeTest(ProviderTestBase):
    def test_create_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value({"a": 1, "b": 2, "sum": None, "product": None}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.PlanResourceChange.Response)
        self.assert_no_diagnostic_errors(resp)

        self.assertEqual(
            resp.planned_state,
            to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown}),
        )

        self.assertEqual(resp.requires_replace, [])
        self.assertEqual(resp.planned_private, b"")
        self.assertEqual(resp.legacy_type_system, False)

    def test_create_default_value(self):
        """Verify CREATE with an attribute with a default value"""
        provider, servicer, ctx = self.provider_servicer_context(DefaultAttributeProvider)
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math_with_default",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value(
                    {"a": 1, "b": 2, "sum": None, "product": None, "c_with_default": None}
                ),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.PlanResourceChange.Response)
        self.assert_no_diagnostic_errors(resp)

        self.assertEqual(
            resp.planned_state,
            to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown, "c_with_default": 9001}),
        )

        self.assertEqual(resp.requires_replace, [])
        self.assertEqual(resp.planned_private, b"")
        self.assertEqual(resp.legacy_type_system, False)

    def test_create_no_default_value(self):
        """Verify CREATE with an optional attribute without a default"""
        provider, servicer, ctx = self.provider_servicer_context(DefaultAttributeProvider)
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math_without_default",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value(
                    {"a": 1, "b": 2, "sum": None, "product": None, "c_without_default": None}
                ),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.PlanResourceChange.Response)
        self.assert_no_diagnostic_errors(resp)

        self.assertEqual(
            resp.planned_state,
            to_dynamic_value(
                {"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown, "c_without_default": None}
            ),
        )

        self.assertEqual(resp.requires_replace, [])
        self.assertEqual(resp.planned_private, b"")
        self.assertEqual(resp.legacy_type_system, False)

    def test_delete_verify_impossible(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math",
                prior_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                proposed_new_state=to_dynamic_value(None),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="DELETE should never be sent to PlanResourceChange",
                        detail="This is a bug in the Plugin SDK",
                    ),
                ]
            ),
        )

    def test_update_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math",
                # Are these prior/proposed states for computed actually provided? Or are they Unknown?
                prior_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                proposed_new_state=to_dynamic_value({"a": 2, "b": 2, "sum": 3, "product": 2}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                # Maybe this should be Unknown?
                planned_state=to_dynamic_value({"a": 2, "b": 2, "sum": 3, "product": 2}),
                requires_replace=[],
                planned_private=b"",
                legacy_type_system=False,
            ),
        )

    # TODO(Hunter): Add test for no fields change

    def test_requires_replace(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math",
                # Are these prior/proposed states for computed actually provided? Or are they Unknown?
                prior_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                proposed_new_state=to_dynamic_value({"a": 1, "b": 3, "sum": 3, "product": 2}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                # Maybe this should be Unknown?
                planned_state=to_dynamic_value({"a": 1, "b": 3, "sum": 3, "product": 2}),
                requires_replace=[
                    pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="b")]),
                ],
                planned_private=b"",
                legacy_type_system=False,
                diagnostics=[],
            ),
        )

    def test_error_impossible(self):
        # planned = current = None
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_math",
                # Are these prior/proposed states for computed actually provided? Or are they Unknown?
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value(None),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Both prior_state and proposed_new_state are None",
                        detail="We should never be send this by TF.",
                    ),
                ],
            ),
        )

    def test_canonicalized_json(self):
        """Updates to json with different whitespace should be reflected"""
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_json",
                # Are these prior/proposed states for computed actually provided? Or are they Unknown?
                prior_state=to_dynamic_value({"json": '   {  \t\n "weird whitespace":    true}   '}),
                proposed_new_state=to_dynamic_value({"json": '{"weird whitespace":true}'}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.planned_state)

        # If the update forces the field to change empty whitespace, that still counts
        # and Terraform should show it to the user as eg
        # ~ form_schema_template = jsonencode( # whitespace changes
        self.assertEqual(
            new_state["json"],
            '{"weird whitespace":true}',
        )

    def test_create_nested_block_set_empty(self):
        """Verify plan when a NestedSetBlock is used but no values are provided"""
        # Default config/state value for nested set block with no provided values is []
        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_has_set_block",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value({"set_block": []}),
                config=to_dynamic_value({"set_block": []}),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.planned_state)
        self.assertEqual([], new_state["set_block"])

    def test_create_nested_block_set_filled(self):
        """Verify plan when a NestedSetBlock is used with values"""
        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)

        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_has_set_block",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value({"set_block": [{"name": "a", "value": 1}]}),
                config=to_dynamic_value({"set_block": [{"name": "a", "value": 1}]}),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.planned_state)
        self.assertEqual([{"name": "a", "value": 1}], new_state["set_block"])

    def test_existing_state_decode_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_json",
                prior_state=to_dynamic_value({"json": "not a valid json"}),
                proposed_new_state=to_dynamic_value({"json": "1"}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Failed to decode field 'json'",
                        detail="Error decoding field 'json': Error parsing JSON: Expecting value: line 1 column 1 (char 0)",
                        attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="json")]),
                    ),
                ],
            ),
        )

    def test_new_state_decoding_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.PlanResourceChange(
            pb.PlanResourceChange.Request(
                type_name="test_json",
                prior_state=to_dynamic_value(None),
                proposed_new_state=to_dynamic_value({"json": "not a valid json"}),
                config=to_dynamic_value(None),
                prior_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.PlanResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Failed to decode field 'json'",
                        detail="Error decoding field 'json': Error parsing JSON: Expecting value: line 1 column 1 (char 0)",
                        attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="json")]),
                    ),
                ],
            ),
        )


class ApplyResourceChangeTest(ProviderTestBase):
    def test_create_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_math",
                prior_state=to_dynamic_value(None),
                planned_state=to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.res_create.assert_called_once()
        call_context = self.res_create.call_args[0][0]
        call_state = self.res_create.call_args[0][1]
        self.assertEqual(call_context.type_name, "test_math")
        self.assertEqual(call_state, {"a": 1, "b": 2, "sum": 3, "product": 2})

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                private=b"",
            ),
        )

    def test_create_nested_block_set_filled(self):
        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)

        with mock.patch.object(HasSetBlockResource, "mock_create") as mock_create:
            resp = servicer.ApplyResourceChange(
                pb.ApplyResourceChange.Request(
                    type_name="test_has_set_block",
                    prior_state=to_dynamic_value(None),
                    planned_state=to_dynamic_value(
                        {
                            "set_block": [
                                {"name": "a", "value": 1},
                                {"name": "b", "value": 2},
                            ]
                        }
                    ),
                    config=to_dynamic_value(
                        {
                            "set_block": [
                                {"name": "a", "value": 1},
                                {"name": "b", "value": 2},
                            ]
                        }
                    ),
                    planned_private=b"",
                    provider_meta={},
                ),
                ctx,
            )

        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual(
            [
                {"name": "a", "value": 1},
                {"name": "b", "value": 2},
            ],
            new_state["set_block"],
        )

        self.assertEqual(
            mock_create.call_args.args[1],
            {"set_block": [{"name": "a", "value": 1}, {"name": "b", "value": 2}]},
        )

    def test_create_complex_types_planned_unknown(self):
        """Verify complex fields can be created when their planned value is Unknown (computed)"""
        provider, service, ctx = self.provider_servicer_context()
        request = pb.ApplyResourceChange.Request(
            type_name="test_complex",
            prior_state=to_dynamic_value(None),
            planned_state=to_dynamic_value({"favorite_numbers": Unknown}),
            config=to_dynamic_value({"favorite_numbers": None}),
            planned_private=b"",
            provider_meta={},
        )

        with mock.patch.object(CustomTypeStrictSet, "on_check_semantic_equality") as check_sem_eq:
            resp = service.ApplyResourceChange(request, ctx)

        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual({7, 8, 9}, set(new_state["favorite_numbers"]))

        # There was no reason to call compare semantic equality, as there was a Unknown in the plan.
        # (And even if we do later, NONE of the calls should have Unknown in them)
        check_sem_eq.assert_not_called()

    @patch("sys.stderr", new_callable=StringIO)
    def test_wrap_encoding_errors(self, stderr_mock):
        """Verify exceptions raised during encoding reveal which field caused it"""
        # This is a catastrophic error that should never happen, but if it does we'd like some breadcrumbs
        provider, servicer, ctx = self.provider_servicer_context()

        request = pb.ApplyResourceChange.Request(
            type_name="test_complex",
            prior_state=to_dynamic_value(None),
            planned_state=to_dynamic_value({"favorite_numbers": Unknown}),
            config=to_dynamic_value({"favorite_numbers": Unknown}),
            planned_private=b"",
            provider_meta={},
        )

        with mock.patch.object(CustomTypeStrictSet, "encode") as mock_encode:
            mock_encode.side_effect = ValueError("Something bad happened during encoding!")

            with self.assertRaises(p.EncodeError) as raised:
                servicer.ApplyResourceChange(request, ctx)

        self.assertIn(
            "Failed to encode field 'favorite_numbers': ValueError: Something bad happened during encoding!",
            str(raised.exception),
        )

    def test_update_nested_block_unchanged_set_comparison(self):
        """Verify set-comparison semantics for nested block sets"""
        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)

        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_has_set_block",
                prior_state=to_dynamic_value(
                    {
                        "set_block": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                        ]
                    }
                ),
                planned_state=to_dynamic_value(
                    {
                        "set_block": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                        ]
                    }
                ),
                config=to_dynamic_value(
                    {
                        "set_block": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                        ]
                    }
                ),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual(
            [
                {"name": "a", "value": 1},
                {"name": "b", "value": 2},
            ],
            new_state["set_block"],
        )

    def test_create_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_errorsalot",
                prior_state=to_dynamic_value(None),
                planned_state=to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value({}),
                private=b"",
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Create failed",
                    ),
                ],
            ),
        )

    def test_delete_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_math",
                prior_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                planned_state=to_dynamic_value(None),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value(None),
                private=b"",
            ),
        )

        self.res_delete.assert_called_once()
        call_context = self.res_delete.call_args[0][0]
        call_state = self.res_delete.call_args[0][1]
        self.assertEqual(call_context.type_name, "test_math")
        self.assertEqual(call_state, {"a": 1, "b": 2, "sum": 3, "product": 2})

    def test_delete_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_errorsalot",
                prior_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                planned_state=to_dynamic_value(None),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value(None),
                private=b"",
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Delete failed",
                    ),
                ],
            ),
        )

    def test_update_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_math",
                prior_state=to_dynamic_value({"a": 1, "b": 3, "sum": 4, "product": 3}),
                planned_state=to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.res_update.assert_called_once()
        call_context = self.res_update.call_args[0][0]
        current_state = self.res_update.call_args[0][1]
        planned_state = self.res_update.call_args[0][2]
        self.assertEqual(call_context.type_name, "test_math")
        self.assertEqual(current_state, {"a": 1, "b": 3, "sum": 4, "product": 3})
        self.assertEqual(planned_state, {"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown})

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                private=b"",
            ),
        )

    def test_update_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_errorsalot",
                prior_state=to_dynamic_value({"a": 1, "b": 3, "sum": 4, "product": 3}),
                planned_state=to_dynamic_value({"a": 1, "b": 2, "sum": types.Unknown, "product": types.Unknown}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                new_state=to_dynamic_value(None),
                private=b"",
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Update failed",
                    ),
                ],
            ),
        )

    def test_update_canonicalized_json(self):
        """Verify byte-for-byte return value if semantic equivalence of json field hasn't changed"""
        # This property allows us to make JSON fields turn in dicts in Python land while also
        # allowing Terraform to realize the field hasn't changed
        #
        # Since our JsonResource returns the same value that was passed in, a naive
        # implementation would serialize the json and lose the whitespace information.
        # This test shows that if the values are semantically equivalent, we preserve the whitespace
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_json",
                prior_state=to_dynamic_value({"json": Unknown}),
                planned_state=to_dynamic_value({"json": '{     "weird whitespace": \n true}'}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual(new_state["json"], '{     "weird whitespace": \n true}')

    def test_existing_state_decode_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_json",
                prior_state=to_dynamic_value({"json": "not a valid json"}),
                planned_state=to_dynamic_value({"json": "1"}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Failed to decode field 'json'",
                        detail="Error decoding field 'json': Error parsing JSON: Expecting value: line 1 column 1 (char 0)",
                        attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="json")]),
                    ),
                ],
            ),
        )

    def test_new_state_decoding_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ApplyResourceChange(
            pb.ApplyResourceChange.Request(
                type_name="test_json",
                prior_state=to_dynamic_value({"json": "1"}),
                planned_state=to_dynamic_value({"json": "not valid json"}),
                config=to_dynamic_value(None),
                planned_private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ApplyResourceChange.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Failed to decode field 'json'",
                        detail="Error decoding field 'json': Error parsing JSON: Expecting value: line 1 column 1 (char 0)",
                        attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="json")]),
                    ),
                ],
            ),
        )

    def test_update_json_semantic_change(self):
        """Test semantic change in JSON that requires re-encoding"""
        provider, servicer, ctx = self.provider_servicer_context()

        # First create a JsonResource that modifies the value slightly
        class ModifyingJsonResource(JsonResource):
            def update(self, ctx: UpdateContext, current: State, planned: State) -> Optional[State]:
                # Return a slightly modified version to trigger re-encoding
                result = planned.copy()
                if "json" in result:
                    # The value is already a dict here, not a string
                    data = result["json"].copy() if isinstance(result["json"], dict) else {"value": result["json"]}
                    data["modified"] = True
                    result["json"] = data
                return result

        # Load the resource class map first
        servicer._load_res_cls_map()

        # Temporarily replace the resource class
        original_cls = servicer._res_cls_map["test_json"]
        servicer._res_cls_map["test_json"] = ModifyingJsonResource

        try:
            resp = servicer.ApplyResourceChange(
                pb.ApplyResourceChange.Request(
                    type_name="test_json",
                    prior_state=to_dynamic_value({"json": '{"a": 1}'}),
                    planned_state=to_dynamic_value({"json": '{"a": 1}'}),
                    config=to_dynamic_value({"json": '{"a": 1}'}),
                ),
                ctx,
            )

            self.assert_no_diagnostic_errors(resp)
            new_state = read_dynamic_value(resp.new_state)
            # Should have the modified value
            self.assertEqual(new_state["json"], '{"a": 1, "modified": true}')
        finally:
            # Restore original class
            servicer._res_cls_map["test_json"] = original_cls


class ReadResourceTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_math",
                current_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.res_read.assert_called_once()
        call_context = self.res_read.call_args[0][0]
        call_state = self.res_read.call_args[0][1]
        self.assertEqual(call_context.type_name, "test_math")
        self.assertEqual(call_state, {"a": 1, "b": 2, "sum": 3, "product": 2})

        self.assertEqual(
            resp,
            pb.ReadResource.Response(
                new_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
            ),
        )

    def test_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_errorsalot",
                current_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ReadResource.Response(
                new_state=to_dynamic_value(None),
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Read failed",
                    ),
                ],
            ),
        )

    def test_invalid_call_no_state(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_math",
                current_state=to_dynamic_value(None),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ReadResource.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="ReadResource test_math called with no state",
                        detail="This is a bug in the Plugin SDK",
                    ),
                ],
            ),
        )

    def test_canonicalized_json(self):
        """Verify byte-for-byte whitespace preservation on semantic equivalence"""
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_json",
                current_state=to_dynamic_value({"json": '{     "weird whitespace": \n true}'}),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual(new_state["json"], '{     "weird whitespace": \n true}')

    def test_canonicalized_nested_block_sets(self):
        """Verify SetNestedBlock canonicalization"""
        # Verify that elements are correct even when the real state drifts from planned

        provider, servicer, ctx = self.provider_servicer_context(ComplexBlocksProvider)
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_has_set_block",
                current_state=to_dynamic_value(
                    {
                        "set_block": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                        ]
                    }
                ),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assert_no_diagnostic_errors(resp)
        new_state = read_dynamic_value(resp.new_state)
        self.assertEqual(
            [
                {"name": "a", "value": 2},
                {"name": "b", "value": 2},
            ],
            new_state["set_block"],
        )

    def test_existing_state_undecodable(self):
        """Verify error diagnostics when existing state has undecodable field"""
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadResource(
            pb.ReadResource.Request(
                type_name="test_json",
                current_state=to_dynamic_value({"json": "not valid json"}),
                private=b"",
                provider_meta={},
            ),
            ctx,
        )
        self.assertEqual(
            resp,
            pb.ReadResource.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Failed to decode field 'json'",
                        detail="Error decoding field 'json': Error parsing JSON: Expecting value: line 1 column 1 (char 0)",
                        attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="json")]),
                    )
                ],
            ),
        )


class ValidateResourceConfigTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateResourceConfig(
            pb.ValidateResourceConfig.Request(
                type_name="test_math",
                config=to_dynamic_value({"a": 1, "b": 2}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateResourceConfig.Response)
        self.assert_no_diagnostic_errors(resp)

    def test_enforce_read_only(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateResourceConfig(
            pb.ValidateResourceConfig.Request(
                type_name="test_math",
                config=to_dynamic_value({"a": 1, "b": 2, "product": 3}),  # setting product (read-only)
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateResourceConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Field test_math.product is read-only and should not be set",
                    attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="product")]),
                )
            ],
        )

    def test_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateResourceConfig(
            pb.ValidateResourceConfig.Request(
                type_name="test_errorsalot",
                config=to_dynamic_value({"a": 1, "b": "not a number"}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateResourceConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Validate failed",
                )
            ],
        )


class ValidateDataResourceConfigTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateDataResourceConfig(
            pb.ValidateDataResourceConfig.Request(
                type_name="test_favorite_number",
                config=to_dynamic_value({}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateDataResourceConfig.Response)
        self.assert_no_diagnostic_errors(resp)

    def test_checks_unknown_field(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateDataResourceConfig(
            pb.ValidateDataResourceConfig.Request(
                type_name="test_favorite_number",
                config=to_dynamic_value({"unknown": 42}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateDataResourceConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Unknown field test_favorite_number.unknown",
                    detail="The field 'unknown' was supplied, but is not a valid field for test_favorite_number."
                    " This is likely a bug in your state file."
                    " If you did not manually edit state, please report this to your provider.",
                )
            ],
        )

    def test_checks_read_only(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateDataResourceConfig(
            pb.ValidateDataResourceConfig.Request(
                type_name="test_favorite_number",
                config=to_dynamic_value({"number": 42}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateDataResourceConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Field test_favorite_number.number is read-only and should not be set",
                    attribute=pb.AttributePath(steps=[pb.AttributePath.Step(attribute_name="number")]),
                )
            ],
        )

    def test_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ValidateDataResourceConfig(
            pb.ValidateDataResourceConfig.Request(
                type_name="test_favorite_number_errors",
                config=to_dynamic_value({}),
            ),
            ctx,
        )

        self.assertIsInstance(resp, pb.ValidateDataResourceConfig.Response)
        self.assertEqual(
            resp.diagnostics,
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="Validate failed",
                )
            ],
        )


class ReadDataSourceTest(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadDataSource(
            pb.ReadDataSource.Request(
                type_name="test_favorite_number",
                config=to_dynamic_value({}),
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ReadDataSource.Response(
                state=to_dynamic_value({"number": 42}),
            ),
        )

    def test_error(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ReadDataSource(
            pb.ReadDataSource.Request(
                type_name="test_favorite_number_errors",
                config=to_dynamic_value({}),
                provider_meta={},
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ReadDataSource.Response(
                state=to_dynamic_value(None),
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="Read failed",
                    ),
                ],
            ),
        )


class ImportResourceState(ProviderTestBase):
    def test_happy(self):
        provider, servicer, ctx = self.provider_servicer_context(ExampleImportingProvider)
        resp = servicer.ImportResourceState(
            pb.ImportResourceState.Request(
                type_name="test_math",
                id="123_456",
            ),
            ctx,
        )

        self.assertEqual([], resp.diagnostics)
        self.assertEqual(resp.imported_resources[0].type_name, "test_math")
        self.assertEqual(
            read_dynamic_value(resp.imported_resources[0].state),
            {
                "some_json": '{"wow": {"thats": ["a", "lot", "of", "json", 5]}}',
                "you_imported": "123_456",
            },
        )

    def test_unsupported_resource(self):
        """Verify when resource does not implement import"""
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.ImportResourceState(
            pb.ImportResourceState.Request(
                type_name="test_math",
                id="test_id",
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.ImportResourceState.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="test_math does not support resource import",
                        detail="This provider has not implemented import_ for test_math",
                    ),
                ],
            ),
        )


class MoveResourceState(ProviderTestBase):
    def test_not_implemented(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.MoveResourceState(
            pb.MoveResourceState.Request(),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.MoveResourceState.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="MoveResourceState is not implemented",
                        detail="MoveResourceState is not implemented",
                    ),
                ],
            ),
        )


class GetFunctionsTest(ProviderTestBase):
    def test_not_implemented(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.GetFunctions(
            pb.GetFunctions.Request(),
            ctx,
        )

        # Since functions are now implemented, it should return an empty functions map
        # when the provider has no functions
        self.assertEqual(
            resp,
            pb.GetFunctions.Response(
                functions={},
                diagnostics=[],
            ),
        )


class CallFunctionTest(ProviderTestBase):
    def test_function_not_found(self):
        provider, servicer, ctx = self.provider_servicer_context()

        resp = servicer.CallFunction(
            pb.CallFunction.Request(name="nonexistent_func", arguments=[]),
            ctx,
        )

        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.text, "Function 'nonexistent_func' not found")

    def test_too_many_arguments(self):
        # Create a test function with fixed parameters
        from tf.function import Function, FunctionSignature, Parameter, Return
        from tf.types import Number

        class TestFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "test_func"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[Parameter(name="a", type=Number())],
                    return_type=Return(type=Number()),
                )

            def call(self, ctx, arguments):
                return arguments[0] * 2

        provider = Mock()
        provider.get_functions.return_value = [TestFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        # Send too many arguments
        resp = servicer.CallFunction(
            pb.CallFunction.Request(
                name="test_func",
                arguments=[
                    pb.DynamicValue(msgpack=msgpack.packb(5)),
                    pb.DynamicValue(msgpack=msgpack.packb(10)),  # Extra argument
                ],
            ),
            ctx,
        )

        self.assertIsNotNone(resp.error)
        self.assertIn("Too many arguments", resp.error.text)
        self.assertEqual(resp.error.function_argument, 1)

    def test_missing_arguments(self):
        # Create a test function requiring parameters
        from tf.function import Function, FunctionSignature, Parameter, Return
        from tf.types import Number

        class TestFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "test_func"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[
                        Parameter(name="a", type=Number()),
                        Parameter(name="b", type=Number()),
                    ],
                    return_type=Return(type=Number()),
                )

            def call(self, ctx, arguments):
                return arguments[0] + arguments[1]

        provider = Mock()
        provider.get_functions.return_value = [TestFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        # Send too few arguments
        resp = servicer.CallFunction(
            pb.CallFunction.Request(
                name="test_func",
                arguments=[pb.DynamicValue(msgpack=msgpack.packb(5))],  # Missing second arg
            ),
            ctx,
        )

        self.assertIsNotNone(resp.error)
        self.assertIn("Missing required arguments", resp.error.text)

    def test_successful_function_call(self):
        from tf.function import Function, FunctionSignature, Parameter, Return
        from tf.types import Number

        class AddFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "add"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[
                        Parameter(name="a", type=Number()),
                        Parameter(name="b", type=Number()),
                    ],
                    return_type=Return(type=Number()),
                )

            def call(self, ctx, arguments):
                return arguments[0] + arguments[1]

        provider = Mock()
        provider.get_functions.return_value = [AddFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        resp = servicer.CallFunction(
            pb.CallFunction.Request(
                name="add",
                arguments=[
                    pb.DynamicValue(msgpack=msgpack.packb(5)),
                    pb.DynamicValue(msgpack=msgpack.packb(3)),
                ],
            ),
            ctx,
        )

        if resp.HasField("error"):
            self.fail(f"Unexpected error: {resp.error.text}")
        result = msgpack.unpackb(resp.result.msgpack)
        self.assertEqual(result, 8)

    def test_function_with_diagnostics(self):
        from tf.function import Function, FunctionSignature, Return
        from tf.types import String

        class ErrorFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "error_func"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[],
                    return_type=Return(type=String()),
                )

            def call(self, ctx, arguments):
                ctx.diagnostics.add_error("Test error", "This is a test")
                return "failed"

        provider = Mock()
        provider.get_functions.return_value = [ErrorFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        resp = servicer.CallFunction(
            pb.CallFunction.Request(name="error_func", arguments=[]),
            ctx,
        )

        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.text, "Test error")

    def test_function_with_exception(self):
        from tf.function import Function, FunctionSignature, Return
        from tf.types import String

        class ExceptionFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "exception_func"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[],
                    return_type=Return(type=String()),
                )

            def call(self, ctx, arguments):
                raise ValueError("Test exception")

        provider = Mock()
        provider.get_functions.return_value = [ExceptionFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        resp = servicer.CallFunction(
            pb.CallFunction.Request(name="exception_func", arguments=[]),
            ctx,
        )

        self.assertIsNotNone(resp.error)
        self.assertIn("Function execution error", resp.error.text)
        self.assertIn("Test exception", resp.error.text)

    def test_variadic_function(self):
        from tf.function import Function, FunctionSignature, Parameter, Return
        from tf.types import String

        class ConcatFunc(Function):
            def __init__(self, provider):
                self.provider = provider

            @classmethod
            def get_name(cls):
                return "concat"

            @classmethod
            def get_signature(cls):
                return FunctionSignature(
                    parameters=[Parameter(name="prefix", type=String())],
                    variadic_parameter=Parameter(name="parts", type=String()),
                    return_type=Return(type=String()),
                )

            def call(self, ctx, arguments):
                if len(arguments) == 0:
                    return ""
                return arguments[0] + "".join(arguments[1:])

        provider = Mock()
        provider.get_functions.return_value = [ConcatFunc]
        provider.new_function = lambda cls: cls(provider)

        servicer = p.ProviderServicer(provider)
        ctx = Mock()

        resp = servicer.CallFunction(
            pb.CallFunction.Request(
                name="concat",
                arguments=[
                    pb.DynamicValue(msgpack=msgpack.packb("Hello")),
                    pb.DynamicValue(msgpack=msgpack.packb(" ")),
                    pb.DynamicValue(msgpack=msgpack.packb("World")),
                ],
            ),
            ctx,
        )

        if resp.HasField("error"):
            self.fail(f"Unexpected error: {resp.error.text}")
        result = msgpack.unpackb(resp.result.msgpack)
        self.assertEqual(result, "Hello World")


class StopProviderTest(ProviderTestBase):
    def test_stop_provider_response(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.StopProvider(pb.StopProvider.Request(), ctx)

        self.assertIsInstance(resp, pb.StopProvider.Response)


class GetMetadataTest(ProviderTestBase):
    def test_metadata_response(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.GetMetadata(pb.GetMetadata.Request(), ctx)

        self.assertIsInstance(resp, pb.GetMetadata.Response)
        self.assertTrue(resp.server_capabilities.plan_destroy)
        self.assertTrue(resp.server_capabilities.get_provider_schema_optional)


class LogErrorsDecoratorTest(ProviderTestBase):
    @patch("sys.stderr", new_callable=StringIO)
    def test_exception_logging(self, mock_stderr):
        """Test that _log_errors decorator logs exceptions"""
        from tf.provider import _log_errors

        @_log_errors
        def failing_method():
            raise ValueError("Test exception")

        with self.assertRaises(ValueError):
            failing_method()

        # Check that traceback was printed
        output = mock_stderr.getvalue()
        self.assertIn("Test exception", output)
        self.assertIn("Traceback", output)


class UpgradeResourceStateTest(ProviderTestBase):
    def test_skip_if_current_version(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.UpgradeResourceState(
            pb.UpgradeResourceState.Request(
                type_name="test_math",
                version=2,
                raw_state=pb.RawState(
                    json=json.dumps({"a": 1, "b": 2, "sum": 3, "product": 2}).encode(),
                ),
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.UpgradeResourceState.Response(
                upgraded_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
            ),
        )

    def test_not_implemented(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.UpgradeResourceState(
            pb.UpgradeResourceState.Request(
                type_name="test_math",
                version=1,
                raw_state=pb.RawState(
                    json=json.dumps({"a": 1, "b": 2, "sum": 3, "product": 2}).encode(),
                ),
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.UpgradeResourceState.Response(
                upgraded_state=to_dynamic_value({"a": 1, "b": 2, "sum": 3, "product": 2}),
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.WARNING,
                        summary="Using default upgrade for test_math.",
                    ),
                ],
            ),
        )

    def test_flat_map_not_supported(self):
        provider, servicer, ctx = self.provider_servicer_context()
        resp = servicer.UpgradeResourceState(
            pb.UpgradeResourceState.Request(
                type_name="test_math",
                version=1,
                raw_state=pb.RawState(
                    flatmap={"xx": "xxx"},
                ),
            ),
            ctx,
        )

        self.assertEqual(
            resp,
            pb.UpgradeResourceState.Response(
                diagnostics=[
                    pb.Diagnostic(
                        severity=pb.Diagnostic.ERROR,
                        summary="UpgradeResourceState is not supported",
                        detail="UpgradeResourceState using flatmap is not supported. This is a bug in the Plugin SDK.",
                    ),
                ],
            ),
        )
