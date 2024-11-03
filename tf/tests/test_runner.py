import contextlib
import io
import json
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
        mock_server.add_registered_method_handlers.assert_called_once()
        self.assertEqual(3, mock_server.wait_for_termination.call_count)

    def test_close_message(self):
        """Verify that we accept a poison pill to stop the server in"""
        message = "/plugin.GRPCController/Shutdown"

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

                if wait_count > 2:
                    shutdown_interceptor.intercept_service(continuation, mock.Mock(method=message))
                else:
                    shutdown_interceptor.intercept_service(
                        continuation, mock.Mock(method="/plugin.GRPCController/Other")
                    )

                return True  # happy to keep spinning

            mock_server.wait_for_termination = wait_for_termination

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                runner.run_provider(provider, ["cmd"])

        out = stdout.getvalue()
        self.assertIn("Stopping server...\n", out)

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

        stdout = io.StringIO()
        with redirect_stdout(stdout) as stdout:
            details = mock.Mock(
                method="/plugin.GRPCController/Shutdown",
            )
            log_interceptor.intercept_service(continuation, details)

        out = stdout.getvalue()
        self.assertIn("Handling call to ", out)


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
