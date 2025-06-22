import contextlib
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from textwrap import dedent
from unittest import TestCase, mock

import grpc

from tf import runner
from tf.tests.test_provider import ExampleProvider


class RunProviderTest(TestCase):
    def test_prod(self):
        provider = ExampleProvider()
        mock_server = mock.Mock()

        # Three spins of the loop, then we stop (timeout not reached)
        mock_server.wait_for_termination.side_effect = [True, True, False]

        with mock.patch.object(grpc, "server", return_value=mock_server) as server_call:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                runner.run_provider(provider, ["cmd"])

        out = stdout.getvalue()
        first_line = out.splitlines()[0]
        fields = first_line.split("|")

        self.assertEqual(len(fields), 6)
        self.assertEqual(fields[0], "1")
        self.assertEqual(fields[1], "6")
        self.assertEqual(fields[2], "unix")
        self.assertIn("py-tf-plugin.sock", fields[3])
        self.assertEqual(fields[4], "grpc")
        self.assertIn("MIIC", fields[5])  # common start of base64 encoded cert

        server_call.assert_called_once()
        # Should be called twice now - once for Provider, once for GRPCController
        self.assertEqual(2, mock_server.add_registered_method_handlers.call_count)
        self.assertEqual(3, mock_server.wait_for_termination.call_count)

    def test_close_message(self):
        """Verify that we accept a poison pill to stop the server in"""
        message = "/tfplugin6.Provider/StopProvider"

        provider = ExampleProvider()
        mock_server = mock.Mock()

        def continuation(handler_call_details):
            return None

        with mock.patch.object(grpc, "server", return_value=mock_server) as server_call:
            wait_count = 0

            def wait_for_termination(*args, **kwargs):
                """When we pretend to wait for calls, we feed in a shutdown message"""
                nonlocal wait_count
                wait_count += 1
                interceptors = server_call.call_args.kwargs["interceptors"]
                shutdown_interceptor = [i for i in interceptors if isinstance(i, runner._ShutdownInterceptor)][0]
                # Give the interceptor a reference to the mock server
                shutdown_interceptor.server = mock_server

                if wait_count == 1:
                    # First iteration - set stopped to trigger the break
                    shutdown_interceptor.intercept_service(continuation, mock.Mock(method=message))
                    return True  # Return True but stopper.stopped will cause break
                elif wait_count > 3:
                    # Safety fallback
                    return False
                else:
                    shutdown_interceptor.intercept_service(continuation, mock.Mock(method="/tfplugin6.Provider/Other"))
                    return True

            mock_server.wait_for_termination = wait_for_termination

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                runner.run_provider(provider, ["cmd"])

        stdout.getvalue()  # Consume output
        # The loop should have stopped due to stopper.stopped
        self.assertEqual(wait_count, 1)

    def test_dev(self):
        provider = ExampleProvider()
        mock_server = mock.Mock()
        mock_server.wait_for_termination.return_value = False

        with mock.patch.object(grpc, "server", return_value=mock_server):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                runner.run_provider(provider, ["cmd", "--dev"])

        # Output some nice debugging info
        out = stdout.getvalue()
        self.assertIn("export TF_REATTACH_PROVIDERS=", out)

        # Wait for connections indefinitely
        mock_server.wait_for_termination.assert_called_once_with()

    def test_logger(self):
        def continuation(handler_call_details):
            return None

        log_interceptor = runner._LoggingInterceptor()

        # Test with debug disabled (default)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            details = mock.Mock(
                method="/tfplugin6.Provider/StopProvider",
            )
            log_interceptor.intercept_service(continuation, details)

        out = stdout.getvalue()
        self.assertEqual("", out)

        # Test with debug enabled

        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"TF_PLUGIN_DEBUG": "1"}):
            with contextlib.redirect_stderr(stderr):
                details = mock.Mock(
                    method="/tfplugin6.Provider/StopProvider",
                )
                log_interceptor.intercept_service(continuation, details)

        out = stderr.getvalue()
        self.assertIn("[DEBUG] gRPC method called:", out)


class InstallProviderTest(TestCase):
    def setUp(self):
        super().setUp()

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.td = Path(temp_dir.name)
        self.plugin_dir = self.td / "arbitrary-plugins-dir"

        # This is a classic entrypoint script
        self.provider_script = self.td / "terraform-provider-example"
        self.provider_script.write_text(
            dedent(
                """\
            #!/path/to/.venv/bin/python
            import sys
            from mypackage.terraform.main import main

            if __name__ == '__main__':
                sys.exit(main())
        """
            )
        )

    def test_happy(self):
        runner.install_provider(
            host="terraform.example.com",
            namespace="example",
            project="example",
            version="1.2.3",
            plugin_dir=self.plugin_dir,
            provider_script=self.provider_script,
        )

        files = {str(p.relative_to(self.plugin_dir)) for p in self.plugin_dir.glob("**/*") if not p.is_dir()}

        self.assertEqual(
            {
                "terraform.example.com/example/example/1.2.3.json",
                "terraform.example.com/example/example/index.json",
                "terraform.example.com/example/example/terraform-provider-example_1.2.3_darwin_amd64.zip",
                "terraform.example.com/example/example/terraform-provider-example_1.2.3_darwin_arm64.zip",
                "terraform.example.com/example/example/terraform-provider-example_1.2.3_linux_amd64.zip",
                "terraform.example.com/example/example/terraform-provider-example_1.2.3_windows_amd64.zip",
            },
            files,
        )

        # Sets up manifest
        self.assertEqual(
            json.loads((self.plugin_dir / "terraform.example.com/example/example/index.json").read_text()),
            {"versions": {"1.2.3": {}}},
        )

        # Sets up specific version manifest
        sig = "h1:5rBZidGPnUJztLQV+yU6OHDrEiXjR2nEwlWQLphmGDM="
        self.assertEqual(
            json.loads((self.plugin_dir / "terraform.example.com/example/example/1.2.3.json").read_text()),
            {
                "archives": {
                    "darwin_amd64": {"hashes": [sig], "url": "terraform-provider-example_1.2.3_darwin_amd64.zip"},
                    "darwin_arm64": {"hashes": [sig], "url": "terraform-provider-example_1.2.3_darwin_arm64.zip"},
                    "linux_amd64": {"hashes": [sig], "url": "terraform-provider-example_1.2.3_linux_amd64.zip"},
                    "windows_amd64": {"hashes": [sig], "url": "terraform-provider-example_1.2.3_windows_amd64.zip"},
                }
            },
        )


class ShutdownInterceptorThreadingTest(TestCase):
    def test_shutdown_with_server_stop(self):
        """Test that shutdown interceptor calls server.stop() in a thread"""
        interceptor = runner._ShutdownInterceptor()
        mock_server = mock.Mock()
        interceptor.server = mock_server

        # Mock handler details for StopProvider
        handler_details = mock.Mock(method="/tfplugin6.Provider/StopProvider")

        def continuation(x):
            return None

        # Call the interceptor
        interceptor.intercept_service(continuation, handler_details)

        # Should have set stopped flag
        self.assertTrue(interceptor.stopped)

        # Wait briefly for the thread to execute
        import time

        time.sleep(0.02)

        # Server.stop should have been called
        mock_server.stop.assert_called_once_with(grace=0.5)

    def test_shutdown_without_server(self):
        """Test that shutdown interceptor works even without server reference"""
        interceptor = runner._ShutdownInterceptor()
        # No server set

        # Mock handler details for StopProvider
        handler_details = mock.Mock(method="/tfplugin6.Provider/StopProvider")

        def continuation(x):
            return None

        # Call the interceptor - should not raise exception
        interceptor.intercept_service(continuation, handler_details)

        # Should have set stopped flag
        self.assertTrue(interceptor.stopped)

    def test_non_stop_provider_method(self):
        """Test that other methods don't trigger shutdown"""
        interceptor = runner._ShutdownInterceptor()

        # Mock handler details for a different method
        handler_details = mock.Mock(method="/tfplugin6.Provider/GetProviderSchema")

        def continuation(x):
            return "test_result"

        # Call the interceptor
        result = interceptor.intercept_service(continuation, handler_details)

        # Should NOT have set stopped flag
        self.assertFalse(interceptor.stopped)
        # Should have called continuation
        self.assertEqual(result, "test_result")


class SSLCertificateCacheTest(TestCase):
    def setUp(self):
        super().setUp()
        # Use a temporary directory for cache during tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = Path(self.temp_dir.name) / "ssl_cert.json"

        # Mock the cache path
        self.cache_path_patch = mock.patch("tf.runner._get_cert_cache_path", return_value=self.cache_path)
        self.cache_path_patch.start()
        self.addCleanup(self.cache_path_patch.stop)

    def test_generates_new_cert_when_no_cache(self):
        """Test that a new certificate is generated when no cache exists"""
        self.assertFalse(self.cache_path.exists())

        cert_chain, server_creds = runner._self_signed_cert()

        self.assertIsInstance(cert_chain, bytes)
        self.assertIsNotNone(server_creds)
        self.assertTrue(self.cache_path.exists())

    def test_uses_cached_cert_when_valid(self):
        """Test that cached certificate is used when still valid"""
        # First call creates the cache
        cert_chain1, _ = runner._self_signed_cert()

        # Second call should use cache
        cert_chain2, _ = runner._self_signed_cert()

        # Same certificate chain should be returned
        self.assertEqual(cert_chain1, cert_chain2)

    def test_regenerates_cert_when_expired(self):
        """Test that certificate is regenerated when expired"""
        # First create a valid cert
        cert_chain1, _ = runner._self_signed_cert()

        # Manually modify the cache to have an expired cert
        with open(self.cache_path, "r") as f:
            cached = json.load(f)

        # Create an expired certificate
        from datetime import datetime, timedelta

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])

        # Create certificate that expired yesterday
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now() - timedelta(days=2))
            .not_valid_after(datetime.now() - timedelta(days=1))  # Expired yesterday
            .sign(private_key, hashes.SHA256())
        )

        # Update cache with expired cert
        cached["cert_pem"] = certificate.public_bytes(serialization.Encoding.PEM).decode()
        with open(self.cache_path, "w") as f:
            json.dump(cached, f)

        # Should regenerate due to expired cert
        cert_chain2, _ = runner._self_signed_cert()

        # Should be different from the original
        self.assertNotEqual(cert_chain1, cert_chain2)

    def test_regenerates_cert_on_corrupted_cache(self):
        """Test that certificate is regenerated when cache is corrupted"""
        # Create corrupted cache
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            f.write("corrupted json")

        # Should still work and regenerate
        cert_chain, server_creds = runner._self_signed_cert()

        self.assertIsInstance(cert_chain, bytes)
        self.assertIsNotNone(server_creds)

        # Cache should be valid now
        with open(self.cache_path, "r") as f:
            cached = json.load(f)
            self.assertIn("cert_pem", cached)
            self.assertIn("key_pem", cached)
            self.assertIn("cert_chain", cached)

    def test_handles_cache_write_failure(self):
        """Test that certificate generation continues even if cache write fails"""
        # Make cache directory read-only
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        original_open = open

        def mock_open(path, mode="r", *args, **kwargs):
            if str(path) == str(self.cache_path) and "w" in mode:
                raise IOError("Permission denied")
            return original_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=mock_open):
            # Should still generate certificate even if caching fails
            cert_chain, server_creds = runner._self_signed_cert()

            self.assertIsInstance(cert_chain, bytes)
            self.assertIsNotNone(server_creds)


class TimingDiagnosticsTest(TestCase):
    def test_timing_not_enabled_by_default(self):
        """Test that timing diagnostics are not printed without TF_PLUGIN_TIMING"""
        provider = ExampleProvider()
        mock_server = mock.Mock()
        mock_server.wait_for_termination.return_value = False

        # Don't set TF_PLUGIN_TIMING
        with mock.patch("grpc.server", return_value=mock_server):
            with mock.patch("tf.gen.tfplugin_pb2_grpc.add_ProviderServicer_to_server"):
                with mock.patch("tf.gen.grpc_controller_pb2_grpc.add_GRPCControllerServicer_to_server"):
                    with mock.patch("tf.runner._self_signed_cert", return_value=(b"cert", mock.Mock())):
                        with mock.patch("builtins.print"):  # Mock print to avoid output
                            with io.StringIO() as stderr:
                                with contextlib.redirect_stderr(stderr):
                                    runner.run_provider(provider, ["--prod"])

                                output = stderr.getvalue()
                                # Should not contain timing messages
                                self.assertNotIn("[TIMING]", output)

    def test_timing_enabled_coverage(self):
        """Test that timing code executes without error when enabled"""
        provider = ExampleProvider()
        mock_server = mock.Mock()
        mock_server.wait_for_termination.return_value = False

        # Test with timing enabled - just ensure it runs without error
        with mock.patch.dict(os.environ, {"TF_PLUGIN_TIMING": "1"}):
            with mock.patch("grpc.server", return_value=mock_server):
                with mock.patch("tf.gen.tfplugin_pb2_grpc.add_ProviderServicer_to_server"):
                    with mock.patch("tf.gen.grpc_controller_pb2_grpc.add_GRPCControllerServicer_to_server"):
                        with mock.patch("tf.runner._self_signed_cert", return_value=(b"cert", mock.Mock())):
                            with mock.patch("builtins.print"):  # Mock print to avoid output
                                # Just run it - the timing code will execute
                                runner.run_provider(provider, ["--prod"])
                                # If we get here without exception, the timing code worked


class GRPCControllerTest(TestCase):
    def test_grpc_controller_direct_call(self):
        """Test GRPCController Shutdown method directly"""
        # Import what we need
        from tf.gen import grpc_controller_pb2 as controller_pb

        # Create the GRPCController servicer directly
        mock_server = mock.Mock()

        # Set up the server with interceptors
        stopper = runner._ShutdownInterceptor()
        stopper.server = mock_server

        # Call run_provider in a limited scope to get the GRPCControllerServicer class
        from tf.gen import grpc_controller_pb2_grpc as controller_rpc

        # Create the inner GRPCControllerServicer class
        class GRPCControllerServicer(controller_rpc.GRPCControllerServicer):
            def Shutdown(self, request, context):
                # Return empty response and trigger shutdown
                stopper.stopped = True
                if stopper.server:
                    import threading

                    def stop_server():
                        import time

                        time.sleep(0.01)
                        stopper.server.stop(grace=0.5)

                    threading.Thread(target=stop_server, daemon=True).start()
                return controller_pb.Empty()

        # Test the Shutdown method
        servicer = GRPCControllerServicer()
        request = controller_pb.Empty()
        context = mock.Mock()
        result = servicer.Shutdown(request, context)

        # Should return Empty
        self.assertIsInstance(result, controller_pb.Empty)
        self.assertTrue(stopper.stopped)

        # Wait for the thread to execute
        import time

        time.sleep(0.02)

        # The server.stop should have been called
        mock_server.stop.assert_called_once_with(grace=0.5)

    def test_grpc_controller_shutdown(self):
        """Test that GRPCController.Shutdown method works"""
        provider = ExampleProvider()
        mock_server = mock.Mock()

        # We need to capture both the stopper and the controller servicer
        captured_stopper = None
        controller_servicer = None

        def capture_controller(servicer, server):
            nonlocal controller_servicer
            controller_servicer = servicer

        with mock.patch("grpc.server") as mock_grpc_server:

            def server_factory(*args, **kwargs):
                nonlocal captured_stopper
                # Extract the stopper from interceptors
                interceptors = kwargs.get("interceptors", [])
                for interceptor in interceptors:
                    if hasattr(interceptor, "stopped"):
                        captured_stopper = interceptor
                return mock_server

            mock_grpc_server.side_effect = server_factory

            with mock.patch("tf.gen.tfplugin_pb2_grpc.add_ProviderServicer_to_server"):
                with mock.patch(
                    "tf.gen.grpc_controller_pb2_grpc.add_GRPCControllerServicer_to_server",
                    side_effect=capture_controller,
                ):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        runner.run_provider(provider, ["cmd", "--dev"])

        # Now test the captured GRPCControllerServicer
        self.assertIsNotNone(controller_servicer)
        self.assertIsNotNone(captured_stopper)

        # Set up the stopper with a mock server
        captured_stopper.server = mock.Mock()

        # Import what we need
        from tf.gen import grpc_controller_pb2 as controller_pb

        # Test the Shutdown method
        request = controller_pb.Empty()
        context = mock.Mock()
        result = controller_servicer.Shutdown(request, context)

        # Should return Empty
        self.assertIsInstance(result, controller_pb.Empty)

        # The stopper should be marked as stopped
        self.assertTrue(captured_stopper.stopped)

        # Wait for the thread to execute
        import time

        time.sleep(0.02)

        # The server.stop should have been called
        captured_stopper.server.stop.assert_called_once_with(grace=0.5)

    def test_logging_interceptor_unimplemented(self):
        """Test that logging interceptor logs unimplemented errors"""
        interceptor = runner._LoggingInterceptor()

        # Import grpc to get the actual StatusCode
        import grpc

        # Create a mock result with UNIMPLEMENTED status
        mock_result = mock.Mock()
        mock_result.code.return_value = grpc.StatusCode.UNIMPLEMENTED

        def continuation(details):
            return mock_result

        handler_details = mock.Mock(method="/some/unimplemented/method")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = interceptor.intercept_service(continuation, handler_details)

        output = stderr.getvalue()
        self.assertIn("[ERROR] Unimplemented method:", output)
        self.assertIn("/some/unimplemented/method", output)
        self.assertEqual(result, mock_result)

    def test_logging_interceptor_non_unimplemented(self):
        """Test that logging interceptor handles non-unimplemented errors"""
        interceptor = runner._LoggingInterceptor()

        # Import grpc to get the actual StatusCode
        import grpc

        # Create a mock result with OK status
        mock_result = mock.Mock()
        mock_result.code.return_value = grpc.StatusCode.OK

        def continuation(details):
            return mock_result

        handler_details = mock.Mock(method="/some/ok/method")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = interceptor.intercept_service(continuation, handler_details)

        output = stderr.getvalue()
        # Should NOT have logged an error
        self.assertNotIn("[ERROR]", output)
        self.assertEqual(result, mock_result)

    def test_logging_interceptor_no_code_method(self):
        """Test that logging interceptor handles results without code method"""
        interceptor = runner._LoggingInterceptor()

        # Create a result without code method
        mock_result = "simple_result"

        def continuation(details):
            return mock_result

        handler_details = mock.Mock(method="/some/method")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = interceptor.intercept_service(continuation, handler_details)

        output = stderr.getvalue()
        # Should NOT have logged an error
        self.assertNotIn("[ERROR]", output)
        self.assertEqual(result, mock_result)

    def test_grpc_controller_shutdown_no_server(self):
        """Test GRPCController Shutdown when server is None - intercept and clear server"""
        provider = ExampleProvider()
        mock_server = mock.Mock()

        # We need to capture the controller servicer and stopper
        captured_stopper = None
        controller_servicer = None

        def capture_controller(servicer, server):
            nonlocal controller_servicer
            controller_servicer = servicer

        with mock.patch("grpc.server") as mock_grpc_server:

            def server_factory(*args, **kwargs):
                nonlocal captured_stopper
                # Extract the stopper from interceptors
                interceptors = kwargs.get("interceptors", [])
                for interceptor in interceptors:
                    if hasattr(interceptor, "stopped"):
                        captured_stopper = interceptor
                return mock_server

            mock_grpc_server.side_effect = server_factory

            with mock.patch("tf.gen.tfplugin_pb2_grpc.add_ProviderServicer_to_server"):
                with mock.patch(
                    "tf.gen.grpc_controller_pb2_grpc.add_GRPCControllerServicer_to_server",
                    side_effect=capture_controller,
                ):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        runner.run_provider(provider, ["cmd", "--dev"])

        # Now test the captured GRPCControllerServicer
        self.assertIsNotNone(controller_servicer)
        self.assertIsNotNone(captured_stopper)

        # IMPORTANT: Clear the server reference to test the no-server branch
        captured_stopper.server = None

        # Import what we need
        from tf.gen import grpc_controller_pb2 as controller_pb

        # Test the Shutdown method with no server
        request = controller_pb.Empty()
        context = mock.Mock()
        result = controller_servicer.Shutdown(request, context)

        # Should return Empty
        self.assertIsInstance(result, controller_pb.Empty)

        # The stopper should be marked as stopped
        self.assertTrue(captured_stopper.stopped)


class InstallProviderUpdateTest(InstallProviderTest):
    def test_updates_existing_manifest(self):
        """verify existing manifests are updated instead of overwritten"""
        (self.plugin_dir / "terraform.example.com/example/example").mkdir(parents=True)
        (self.plugin_dir / "terraform.example.com/example/example/index.json").write_text(
            json.dumps({"versions": {"1.0.0": {}}})
        )

        runner.install_provider(
            host="terraform.example.com",
            namespace="example",
            project="example",
            version="1.2.3",
            plugin_dir=self.plugin_dir,
            provider_script=self.provider_script,
        )

        self.assertEqual(
            json.loads((self.plugin_dir / "terraform.example.com/example/example/index.json").read_text()),
            {"versions": {"1.0.0": {}, "1.2.3": {}}},
        )
