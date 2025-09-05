import functools
import json
import traceback
from copy import deepcopy
from typing import Any, Optional, Tuple, Type, cast

import grpc

from tf.function import CallContext, Function
from tf.gen import tfplugin_pb2 as pb
from tf.gen import tfplugin_pb2_grpc as rpc
from tf.iface import (
    CreateContext,
    DataSource,
    DeleteContext,
    ImportContext,
    PlanContext,
    Provider,
    ReadContext,
    ReadDataContext,
    Resource,
    UpdateContext,
    UpgradeContext,
    is_importable,
)
from tf.schema import Attribute, NestedBlock
from tf.types import Unknown
from tf.utils import Diagnostic, Diagnostics, _to_attribute_path, read_dynamic_value, to_dynamic_value


def _decode_state(
    diags: Diagnostics,
    attrs: dict[str, Attribute],
    blocks: dict[str, NestedBlock],
    state: pb.DynamicValue | dict[str, Any],
) -> Tuple[Optional[dict], Optional[dict]]:
    st = read_dynamic_value(state) if isinstance(state, pb.DynamicValue) else state

    if st is None:
        return None, None

    def try_decode(field_name: str, decode_f, v: Any) -> Any:
        try:
            return decode_f(v)
        except Exception as exc:
            diags.add_error(
                f"Failed to decode field '{field_name}'",
                detail=f"Error decoding field '{field_name}': {exc}",
                path=[field_name],
            )

            return Unknown

    attr_state = {
        k: try_decode(k, attrs[k].type.decode, v) if v is not Unknown else v for k, v in st.items() if k in attrs
    }
    block_state = {
        k: try_decode(k, blocks[k].decode, v) if v is not Unknown else v for k, v in st.items() if k in blocks
    }

    return st, {**attr_state, **block_state}


def _encode_state_d(
    attrs: dict[str, Attribute],
    blocks: dict[str, NestedBlock],
    state: Optional[dict],
    old: Optional[dict],
) -> dict[str, Any] | None:
    """If any encoded values of state matches the old state, we will use the old state's encoded value"""
    # This preserves byte-for-byte equality for JSON

    if state is None:
        return None

    encoded = {}

    for k, v in state.items():
        try:
            if v is Unknown:
                encoded[k] = Unknown
            elif k in attrs:
                # Check if we can reuse the old encoded value
                if old and k in old:
                    # For simple types, compare encoded values directly
                    if attrs[k].type.__class__.__name__ in ("Number", "String", "Bool"):
                        new_encoded = attrs[k].type.encode(v)
                        if old[k] == new_encoded:
                            encoded[k] = old[k]
                        else:
                            encoded[k] = new_encoded

                    # If the previous value was Unknown and the new one is not, we just accept the new one
                    elif old[k] is Unknown:
                        encoded[k] = attrs[k].type.encode(v)

                    # For complex types, use semantic equality
                    elif attrs[k].type.semantically_equal(attrs[k].type.decode(old[k]), v):
                        encoded[k] = old[k]
                    else:
                        encoded[k] = attrs[k].type.encode(v)
                else:
                    encoded[k] = attrs[k].type.encode(v)
            else:
                # block
                if old and k in old and blocks[k].semantically_equal(blocks[k].decode(old[k]), v):
                    encoded[k] = old[k]
                else:
                    encoded[k] = blocks[k].encode(v)
        except Exception as exc:
            raise EncodeError(f"Failed to encode field '{k}': {type(exc).__name__}: {exc}") from exc

    return encoded


def _encode_state(
    attrs: dict[str, Attribute], blocks: dict[str, NestedBlock], state: Optional[dict], old: Optional[dict]
) -> pb.DynamicValue:
    """If any encoded values of state matches the old state, we will use the old state's encoded value"""
    # This preserves byte-for-byte equality for JSON
    return to_dynamic_value(_encode_state_d(attrs, blocks, state, old))


def _log_errors(f):
    """Decorator because there is no global try/catch mechanism in grpc??"""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            traceback.print_exc()
            raise

    return wrapper


class ProviderServicer(rpc.ProviderServicer):
    def __init__(self, app: Provider):
        self.app = app
        self._ds_cls_map: Optional[dict[str, Type[DataSource]]] = None
        self._res_cls_map: Optional[dict[str, Type[Resource]]] = None
        self._func_cls_map: Optional[dict[str, Type[Function]]] = None

        # Getting a resource's attributes in k-v form is very common, want to cache
        self._res_attr_map: dict[str, dict[str, Attribute]] = {}
        # Sam for res blocks
        self._res_block_map: dict[str, dict[str, NestedBlock]] = {}

        # Cache for schemas to avoid repeated computation
        self._ds_schema_cache: dict[str, Any] = {}
        self._res_schema_cache: dict[str, Any] = {}

    def _load_ds_cls_map(self) -> dict[str, Type[DataSource]]:
        if self._ds_cls_map is None:
            prefix = self.app.get_model_prefix()
            self._ds_cls_map = {prefix + ds.get_name(): ds for ds in self.app.get_data_sources()}

        return self._ds_cls_map

    def _get_ds_cls(self, type_name: str) -> Type[DataSource]:
        return self._load_ds_cls_map()[type_name]

    def _load_res_cls_map(self) -> dict[str, Type[Resource]]:
        if self._res_cls_map is None:
            prefix = self.app.get_model_prefix()
            self._res_cls_map = {prefix + res.get_name(): res for res in self.app.get_resources()}

        return self._res_cls_map

    def _get_res_cls(self, type_name: str) -> Type[Resource]:
        return self._load_res_cls_map()[type_name]

    def _get_res_attrs(self, type_name: str) -> dict[str, Attribute]:
        if type_name not in self._res_attr_map:
            klass = self._get_res_cls(type_name)
            self._res_attr_map[type_name] = {a.name: a for a in klass.get_schema().attributes}

        return self._res_attr_map[type_name]

    def _get_res_blocks(self, type_name: str) -> dict[str, NestedBlock]:
        if type_name not in self._res_block_map:
            klass = self._get_res_cls(type_name)
            self._res_block_map[type_name] = {b.type_name: b for b in klass.get_schema().block_types}

        return self._res_block_map[type_name]

    def _load_func_cls_map(self) -> dict[str, Type[Function]]:
        if self._func_cls_map is None:
            self._func_cls_map = {func.get_name(): func for func in self.app.get_functions()}

        return self._func_cls_map

    def _get_func_cls(self, name: str) -> Type[Function]:
        return self._load_func_cls_map()[name]

    @_log_errors
    def GetMetadata(self, request: pb.GetMetadata.Request, context: grpc.ServicerContext):
        # Return empty metadata - this is called by Terraform to check capabilities
        return pb.GetMetadata.Response(
            server_capabilities=pb.ServerCapabilities(
                # We support plan_destroy for proper cleanup
                plan_destroy=True,
                # GetProviderSchemaOptional indicates we can handle GetProviderSchema being called
                # conditionally based on whether Terraform has a cached schema
                get_provider_schema_optional=True,
            )
        )

    # ----------------- Provider ----------------- #
    @_log_errors
    def GetProviderSchema(self, request: pb.GetProviderSchema.Request, context: grpc.ServicerContext):
        diags = Diagnostics()
        schema = self.app.get_provider_schema(diags).to_pb()
        self._load_ds_cls_map()
        self._load_res_cls_map()
        self._load_func_cls_map()

        # Use cached schemas
        ds_schemas = {}
        for type_name, klass in self._load_ds_cls_map().items():
            if type_name not in self._ds_schema_cache:
                self._ds_schema_cache[type_name] = klass.get_schema().to_pb()
            ds_schemas[type_name] = self._ds_schema_cache[type_name]

        res_schema = {}
        for type_name, klass in self._load_res_cls_map().items():
            if type_name not in self._res_schema_cache:
                self._res_schema_cache[type_name] = klass.get_schema().to_pb()
            res_schema[type_name] = self._res_schema_cache[type_name]

        func_schemas = {name: klass.get_signature().to_pb() for name, klass in self._load_func_cls_map().items()}

        # Create a proper provider_meta schema
        # This is an empty schema with an empty block - valid but with no attributes
        provider_meta = pb.Schema(
            version=0,
            block=pb.Schema.Block(
                version=0,
                attributes=[],
                block_types=[],
                description="",
                description_kind=pb.PLAIN,
                deprecated=False,
            ),
        )

        resp = pb.GetProviderSchema.Response(
            provider=schema,
            provider_meta=provider_meta,
            diagnostics=diags.to_pb(),
            data_source_schemas=ds_schemas,
            resource_schemas=res_schema,
            functions=func_schemas,
        )
        return resp

    @_log_errors
    def ValidateProviderConfig(self, request: pb.ValidateProviderConfig.Request, context: grpc.ServicerContext):
        R = pb.ValidateProviderConfig.Response
        diags = Diagnostics()
        config = read_dynamic_value(request.config)
        self.app.validate_config(diags, config)
        return R(diagnostics=diags.to_pb())

    @_log_errors
    def ValidateResourceConfig(self, request: pb.ValidateResourceConfig.Request, context: grpc.ServicerContext):
        conf = read_dynamic_value(request.config)
        type_name = request.type_name
        klass = self._get_res_cls(type_name)
        inst = self.app.new_resource(klass)
        diags = Diagnostics()

        inst.validate(diags, type_name, conf)
        return pb.ValidateResourceConfig.Response(diagnostics=diags.to_pb())

    @_log_errors
    def ValidateDataResourceConfig(self, request: pb.ValidateDataResourceConfig.Request, context: grpc.ServicerContext):
        conf = read_dynamic_value(request.config)
        klass = self._get_ds_cls(request.type_name)
        inst = self.app.new_data_source(klass)
        diags = Diagnostics()

        inst.validate(diags, request.type_name, conf)
        return pb.ValidateDataResourceConfig.Response(diagnostics=diags.to_pb())

    @_log_errors
    def UpgradeResourceState(self, request: pb.UpgradeResourceState.Request, context: grpc.ServicerContext):
        diags = Diagnostics()

        if len(request.raw_state.flatmap) != 0:
            # Not sure what this field is for. I need an example to implement this
            diags.add_error(
                "UpgradeResourceState is not supported",
                detail="UpgradeResourceState using flatmap is not supported. This is a bug in the Plugin SDK.",
            )
            return pb.UpgradeResourceState.Response(diagnostics=diags.to_pb())

        state = json.loads(request.raw_state.json)
        klass = self._get_res_cls(request.type_name)
        inst = self.app.new_resource(klass)
        schema = klass.get_schema()

        old_version = request.version
        new_version = schema.version

        if new_version is None or old_version is None or old_version < new_version:
            state = inst.upgrade(UpgradeContext(diags, request.type_name), old_version, deepcopy(state))

        return pb.UpgradeResourceState.Response(
            upgraded_state=to_dynamic_value(state),
            diagnostics=diags.to_pb(),
        )

    # ----------------- One-time init ----------------- #
    @_log_errors
    def ConfigureProvider(self, request: pb.ConfigureProvider.Request, context: grpc.ServicerContext):
        conf = read_dynamic_value(request.config)
        diags = Diagnostics()
        self.app.configure_provider(diags, conf)
        return pb.ConfigureProvider.Response(diagnostics=diags.to_pb())

    # ----------------- Resource Lifecycle ----------------- #
    @_log_errors
    def ReadResource(self, request: pb.ReadResource.Request, context: grpc.ServicerContext):
        diags = Diagnostics()

        type_name = request.type_name
        attrs = self._get_res_attrs(type_name)
        blocks = self._get_res_blocks(type_name)
        current_enc, current_state = _decode_state(diags, attrs, blocks, request.current_state)

        if diags.has_errors():
            return pb.ReadResource.Response(diagnostics=diags.to_pb())

        if current_state is None:
            # I think this is not possible
            diags.add_error(
                f"ReadResource {type_name} called with no state",
                detail="This is a bug in the Plugin SDK",
            )
            return pb.ReadResource.Response(diagnostics=diags.to_pb())

        klass = self._get_res_cls(type_name)
        inst = self.app.new_resource(klass)
        new_state = inst.read(ReadContext(diags, type_name), current_state)

        resp = pb.ReadResource.Response(
            new_state=_encode_state(attrs, blocks, new_state, current_enc),
            diagnostics=diags.to_pb(),
        )
        return resp

    @_log_errors
    def PlanResourceChange(self, request: pb.PlanResourceChange.Request, context: grpc.ServicerContext):
        type_name = request.type_name
        diags = Diagnostics()

        attrs = self._get_res_attrs(type_name)
        blocks = self._get_res_blocks(type_name)
        _, prior_state = _decode_state(diags, attrs, blocks, request.prior_state)
        if diags.has_errors():
            return pb.PlanResourceChange.Response(diagnostics=diags.to_pb())

        proposed_enc, proposed_new_state = _decode_state(diags, attrs, blocks, request.proposed_new_state)
        if diags.has_errors():
            return pb.PlanResourceChange.Response(diagnostics=diags.to_pb())

        # config = read_dynamic_value(request.config)
        # prior_private = request.prior_private

        klass = self._get_res_cls(type_name)
        inst = self.app.new_resource(klass)

        # We simplify the logic here. Instead of requiring each implementing resource to implement
        # plan_resource_change and apply_resource_change, we can figure
        # our what is changing and then map that to resource.(create|update|delete) which is easier to implement.
        # prior_state = None => CREATE
        # proposed_new_state = None => DELETE
        # Otherwise UPDATE

        if prior_state is None and proposed_new_state is not None:
            # We don't need to visit the resource to make a create plan
            # delete nulls = UNKNOWN
            new_state = {}

            for k, v in proposed_new_state.items():
                # IDK I gotta figure out what to do with this
                if k in blocks:
                    new_state[k] = v
                else:
                    # Attribute
                    if v is not None:
                        new_state[k] = v
                    elif not attrs[k].computed:
                        # TF requires non-computed unspecified fields to be set to None as their planned value
                        new_state[k] = None
                    else:
                        new_state[k] = attrs[k].default

            new_state_encoded = _encode_state(attrs, blocks, new_state, proposed_enc)
            return pb.PlanResourceChange.Response(planned_state=new_state_encoded, diagnostics=diags.to_pb())

        # Kind of interesting, TF does not send us DELETE (old_state = SOME and new_state = None)
        if proposed_new_state is None and prior_state is not None:
            diags.add_error(
                "DELETE should never be sent to PlanResourceChange",
                "This is a bug in the Plugin SDK",
            )
            return pb.PlanResourceChange.Response(diagnostics=diags.to_pb())

        if proposed_new_state is None and prior_state is None:
            diags.add_error(
                "Both prior_state and proposed_new_state are None",
                "We should never be send this by TF.",
            )
            return pb.PlanResourceChange.Response(diagnostics=diags.to_pb())

        # Help the type checker out that this is not None
        proposed_new_state = cast(dict, proposed_new_state)
        prior_state = cast(dict, prior_state)

        # Otherwise we have an update
        # We are just going to naively assume that we are going to reach the desired state for planning
        # purposes but check each attribute to see if it requires a replace
        # TODO(Hunter): Wrap this into some common code so we can supply the computed different fields to UpdateContext
        requires_replace = []
        changed_keys = {
            k
            for k in set(proposed_new_state.keys()) & set(prior_state.keys()) & set(attrs.keys())
            if not attrs[k].type.semantically_equal(prior_state[k], proposed_new_state[k])
        }

        for k in changed_keys:
            if attrs[k].requires_replace:
                requires_replace.append(_to_attribute_path([k]))

        # Only deepcopy if states are not None to avoid unnecessary copies
        prior_copy = deepcopy(prior_state) if prior_state is not None else None
        proposed_copy = deepcopy(proposed_new_state) if proposed_new_state is not None else None

        proposed_new_state = inst.plan(
            PlanContext(diags, type_name, changed_fields=changed_keys),
            prior_copy,
            proposed_copy or {},
        )

        return pb.PlanResourceChange.Response(
            planned_state=_encode_state(attrs, blocks, proposed_new_state, proposed_enc),
            requires_replace=requires_replace,
            diagnostics=diags.to_pb(),
        )

    @_log_errors
    def ApplyResourceChange(self, request: pb.ApplyResourceChange.Request, context: grpc.ServicerContext):
        diags = Diagnostics()

        type_name = request.type_name
        attrs = self._get_res_attrs(type_name)
        blocks = self._get_res_blocks(type_name)

        _, prior_state = _decode_state(diags, attrs, blocks, request.prior_state)
        if diags.has_errors():
            return pb.ApplyResourceChange.Response(diagnostics=diags.to_pb())

        planned_enc, planned_state = _decode_state(diags, attrs, blocks, request.planned_state)
        if diags.has_errors():
            return pb.ApplyResourceChange.Response(diagnostics=diags.to_pb())

        klass = self._get_res_cls(type_name)
        inst = self.app.new_resource(klass)

        if prior_state is None and planned_state is not None:
            # Create
            new_state = inst.create(CreateContext(diags, type_name), planned_state)
        elif prior_state is not None and planned_state is None:
            # Delete
            new_state = inst.delete(DeleteContext(diags, type_name), prior_state)
        else:
            prior_state = cast(dict, prior_state)
            planned_state = cast(dict, planned_state)
            new_state = inst.update(UpdateContext(diags, type_name), prior_state, planned_state)

        # We use the planned field values if they are semantically equivalent to the new state.
        # For most fields on update and create, the TF client will have already done the hard work
        # of encoding the field values to provide the planned state.
        # We can skip re-encoding them if they semantically match what we got back from the resource.
        encoded_state = _encode_state(attrs, blocks, new_state, old=planned_enc)

        return pb.ApplyResourceChange.Response(
            new_state=encoded_state,
            diagnostics=diags.to_pb(),
        )

    @_log_errors
    def ImportResourceState(self, request: pb.ImportResourceState.Request, context: grpc.ServicerContext):
        type_name = request.type_name
        klass = self._get_res_cls(type_name)

        if not is_importable(klass):
            diags = Diagnostics().add_error(
                f"{type_name} does not support resource import",
                f"This provider has not implemented import_ for {type_name}",
            )
            return pb.ImportResourceState.Response(diagnostics=diags.to_pb())

        ctx = ImportContext(Diagnostics(), type_name)
        inst = self.app.new_resource(klass)
        state = inst.import_(ctx, request.id)
        attrs = self._get_res_attrs(type_name)
        blocks = self._get_res_blocks(type_name)

        return pb.ImportResourceState.Response(
            imported_resources=(
                [
                    pb.ImportResourceState.ImportedResource(
                        type_name=type_name,
                        state=_encode_state(attrs, blocks, state, old=None),
                    ),
                ]
                if state is not None
                else []
            ),
            diagnostics=ctx.diagnostics.to_pb(),
        )

    @_log_errors
    def MoveResourceState(self, request, context: grpc.ServicerContext):
        diags = Diagnostics().add_error("MoveResourceState is not implemented", "MoveResourceState is not implemented")
        return pb.MoveResourceState.Response(diagnostics=diags.to_pb())

    @_log_errors
    def ReadDataSource(self, request: pb.ReadDataSource.Request, context: grpc.ServicerContext):
        config = read_dynamic_value(request.config)

        klass = self._get_ds_cls(request.type_name)
        inst = self.app.new_data_source(klass)
        diags = Diagnostics()

        state = inst.read(ReadDataContext(diags, request.type_name), config)

        return pb.ReadDataSource.Response(
            diagnostics=diags.to_pb(),
            state=to_dynamic_value(state),
        )

    # ----------------- Functions ----------------- #
    @_log_errors
    def GetFunctions(self, request: pb.GetFunctions.Request, context: grpc.ServicerContext):
        diags = Diagnostics()
        self._load_func_cls_map()
        func_schemas = {name: klass.get_signature().to_pb() for name, klass in self._load_func_cls_map().items()}
        return pb.GetFunctions.Response(functions=func_schemas, diagnostics=diags.to_pb())

    @_log_errors
    def CallFunction(self, request: pb.CallFunction.Request, context: grpc.ServicerContext):
        diags = Diagnostics()

        try:
            func_cls = self._get_func_cls(request.name)
        except KeyError:
            return pb.CallFunction.Response(error=pb.FunctionError(text=f"Function '{request.name}' not found"))

        func_inst = self.app.new_function(func_cls)
        signature = func_cls.get_signature()

        # Decode arguments
        decoded_args = []
        for i, arg in enumerate(request.arguments):
            arg_value = read_dynamic_value(arg)
            if i < len(signature.parameters):
                param = signature.parameters[i]
                decoded_args.append(param.type.decode(arg_value))
            elif signature.variadic_parameter:
                decoded_args.append(signature.variadic_parameter.type.decode(arg_value))
            else:
                return pb.CallFunction.Response(
                    error=pb.FunctionError(
                        text=f"Too many arguments for function '{request.name}'", function_argument=i
                    )
                )

        # Check for missing required arguments
        if len(decoded_args) < len(signature.parameters):
            return pb.CallFunction.Response(
                error=pb.FunctionError(text=f"Missing required arguments for function '{request.name}'")
            )

        # Call the function
        ctx = CallContext(diags, request.name)
        try:
            result = func_inst.call(ctx, decoded_args)

            # Check for diagnostics that would be errors
            if diags.has_errors():
                errors = [d for d in diags.diagnostics if d.severity == Diagnostic.ERROR]
                return pb.CallFunction.Response(
                    error=pb.FunctionError(text=errors[0].summary if errors else "Function call failed")
                )

            # Encode the result
            encoded_result = signature.return_type.type.encode(result)
            return pb.CallFunction.Response(result=to_dynamic_value(encoded_result))
        except Exception as e:
            return pb.CallFunction.Response(error=pb.FunctionError(text=f"Function execution error: {str(e)}"))

    # ----------------- Graceful shutdown ----------------- #
    @_log_errors
    def StopProvider(self, request: pb.StopProvider.Request, context: grpc.ServicerContext):
        # Return empty response to acknowledge shutdown request
        # The actual shutdown is handled by the interceptor and server loop
        return pb.StopProvider.Response()


class EncodeError(Exception):
    pass
