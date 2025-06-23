import unittest
from unittest.mock import Mock

from tf.function import CallContext, Function, FunctionSignature, Parameter, Return
from tf.types import Bool, Number, String
from tf.utils import Diagnostics


class ExampleFunction(Function):
    def __init__(self, provider):
        self.provider = provider

    @classmethod
    def get_name(cls) -> str:
        return "example_add"

    @classmethod
    def get_signature(cls) -> FunctionSignature:
        return FunctionSignature(
            parameters=[
                Parameter(name="a", type=Number(), description="First number"),
                Parameter(name="b", type=Number(), description="Second number"),
            ],
            return_type=Return(type=Number()),
            summary="Add two numbers",
            description="This function adds two numbers together",
        )

    def call(self, ctx: CallContext, arguments: list) -> float:
        return arguments[0] + arguments[1]


class StringFunction(Function):
    def __init__(self, provider):
        self.provider = provider

    @classmethod
    def get_name(cls) -> str:
        return "concat"

    @classmethod
    def get_signature(cls) -> FunctionSignature:
        return FunctionSignature(
            parameters=[
                Parameter(name="prefix", type=String(), description="Prefix string"),
            ],
            variadic_parameter=Parameter(name="parts", type=String(), description="String parts to concatenate"),
            return_type=Return(type=String()),
            summary="Concatenate strings",
        )

    def call(self, ctx: CallContext, arguments: list) -> str:
        if len(arguments) == 0:
            return ""
        return arguments[0] + "".join(arguments[1:])


class ErrorFunction(Function):
    def __init__(self, provider):
        self.provider = provider

    @classmethod
    def get_name(cls) -> str:
        return "error_func"

    @classmethod
    def get_signature(cls) -> FunctionSignature:
        return FunctionSignature(
            parameters=[
                Parameter(name="should_error", type=Bool(), description="Whether to error"),
            ],
            return_type=Return(type=String()),
        )

    def call(self, ctx: CallContext, arguments: list) -> str:
        if arguments[0]:
            ctx.diagnostics.add_error("Function error", "This is a test error")
            return ""
        return "success"


class TestFunctionSignature(unittest.TestCase):
    def test_parameter_to_pb(self):
        param = Parameter(
            name="test",
            type=String(),
            description="Test parameter",
            allow_null_value=True,
            allow_unknown_values=False,
        )
        pb = param.to_pb()

        self.assertEqual(pb.name, "test")
        self.assertEqual(pb.type, b'"string"')
        self.assertEqual(pb.description, "Test parameter")
        self.assertTrue(pb.allow_null_value)
        self.assertFalse(pb.allow_unknown_values)

    def test_return_to_pb(self):
        ret = Return(type=Number())
        pb = ret.to_pb()

        self.assertEqual(pb.type, b'"number"')

    def test_function_signature_to_pb(self):
        sig = FunctionSignature(
            parameters=[
                Parameter(name="a", type=Number()),
                Parameter(name="b", type=String()),
            ],
            return_type=Return(type=Bool()),
            summary="Test function",
            description="This is a test function",
            deprecation_message="This is deprecated",
        )
        pb = sig.to_pb()

        self.assertEqual(len(pb.parameters), 2)
        self.assertEqual(pb.parameters[0].name, "a")
        self.assertEqual(pb.parameters[1].name, "b")
        self.assertEqual(getattr(pb, "return").type, b'"bool"')
        self.assertEqual(pb.summary, "Test function")
        self.assertEqual(pb.description, "This is a test function")
        self.assertEqual(pb.deprecation_message, "This is deprecated")

    def test_variadic_parameter(self):
        sig = FunctionSignature(
            parameters=[
                Parameter(name="first", type=String()),
            ],
            variadic_parameter=Parameter(name="rest", type=Number()),
            return_type=Return(type=String()),
        )
        pb = sig.to_pb()

        self.assertEqual(len(pb.parameters), 1)
        self.assertIsNotNone(pb.variadic_parameter)
        self.assertEqual(pb.variadic_parameter.name, "rest")
        self.assertEqual(pb.variadic_parameter.type, b'"number"')


class TestFunctionImplementation(unittest.TestCase):
    def test_example_function(self):
        func = ExampleFunction(Mock())
        ctx = CallContext(Diagnostics(), "example_add")

        result = func.call(ctx, [5, 3])
        self.assertEqual(result, 8)

        result = func.call(ctx, [10.5, 2.5])
        self.assertEqual(result, 13.0)

    def test_string_function(self):
        func = StringFunction(Mock())
        ctx = CallContext(Diagnostics(), "concat")

        # Test with just prefix
        result = func.call(ctx, ["Hello"])
        self.assertEqual(result, "Hello")

        # Test with variadic args
        result = func.call(ctx, ["Hello", " ", "World", "!"])
        self.assertEqual(result, "Hello World!")

        # Test with empty args
        result = func.call(ctx, [])
        self.assertEqual(result, "")

    def test_error_function(self):
        func = ErrorFunction(Mock())

        # Test success case
        ctx = CallContext(Diagnostics(), "error_func")
        result = func.call(ctx, [False])
        self.assertEqual(result, "success")
        self.assertFalse(ctx.diagnostics.has_errors())

        # Test error case
        ctx = CallContext(Diagnostics(), "error_func")
        result = func.call(ctx, [True])
        self.assertEqual(result, "")
        self.assertTrue(ctx.diagnostics.has_errors())
        self.assertEqual(len(ctx.diagnostics.diagnostics), 1)
        self.assertEqual(ctx.diagnostics.diagnostics[0].summary, "Function error")


class TestFunctionIntegration(unittest.TestCase):
    def test_provider_with_functions(self):
        # Create a mock provider that includes functions
        provider = Mock()
        provider.get_functions.return_value = [ExampleFunction, StringFunction]

        # Test that functions can be retrieved
        functions = provider.get_functions()
        self.assertEqual(len(functions), 2)
        self.assertEqual(functions[0].get_name(), "example_add")
        self.assertEqual(functions[1].get_name(), "concat")

        # Test function instantiation using the default new_function method
        from tf.iface import Provider

        class TestProvider(Provider):
            def get_model_prefix(self) -> str:
                return "test_"

            def get_provider_schema(self, diags):
                from tf.schema import Schema

                return Schema(version=1)

            def full_name(self) -> str:
                return "test.provider"

            def validate_config(self, diags, config):
                pass

            def configure_provider(self, diags, config):
                pass

            def get_data_sources(self):
                return []

            def get_resources(self):
                return []

            def get_functions(self):
                return [ExampleFunction]

        real_provider = TestProvider()
        func_inst = real_provider.new_function(ExampleFunction)
        self.assertIsInstance(func_inst, ExampleFunction)


if __name__ == "__main__":
    unittest.main()
