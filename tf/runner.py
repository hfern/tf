import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from concurrent import futures
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Tuple

# Defer expensive imports - these will be imported when needed
# grpc: ~22.5ms, cryptography: ~20ms, protobuf: ~9-21ms
from tf.iface import Provider


class _LoggingInterceptor:
    """gRPC interceptor for logging"""

    def intercept_service(self, continuation, handler_call_details):
        if os.environ.get("TF_PLUGIN_DEBUG") == "1":
            print(f"[DEBUG] gRPC method called: {handler_call_details.method}", file=sys.stderr)

        # Always log unimplemented errors to help debugging
        result = continuation(handler_call_details)
        if result and hasattr(result, "code") and hasattr(result, "details"):
            # Import grpc here to avoid circular import
            import grpc

            if result.code() == grpc.StatusCode.UNIMPLEMENTED:
                print(f"[ERROR] Unimplemented method: {handler_call_details.method}", file=sys.stderr)

        return result


class _ShutdownInterceptor:
    """gRPC interceptor for handling shutdown"""

    def __init__(self):
        self.stopped = False
        self.server = None  # Will be set when we create the server

    def intercept_service(self, continuation, handler_call_details):
        # Let the call complete first
        result = continuation(handler_call_details)

        # Then handle shutdown after response is sent
        if handler_call_details.method in ["/tfplugin6.Provider/StopProvider", "/plugin.GRPCController/Shutdown"]:
            self.stopped = True
            if self.server:
                # Stop the server immediately after sending response
                self.server.stop(grace=0)

        return result


def run_provider(provider: Provider, argv: Optional[list[str]] = None):
    """
    Run the given provider with the given arguments.

    :param provider: Provider instance to run
    :param argv: Optional arguments to run the provider with
    """
    import time

    start_time = time.time()
    debug_timing = os.environ.get("TF_PLUGIN_TIMING") == "1"

    # Lazy load expensive imports
    import_start = time.time() if debug_timing else 0.0

    import grpc

    from tf.gen import grpc_controller_pb2 as controller_pb
    from tf.gen import grpc_controller_pb2_grpc as controller_rpc
    from tf.gen import tfplugin_pb2_grpc as rpc
    from tf.provider import ProviderServicer

    if debug_timing:
        import_time = time.time() - import_start
        print(f"[TIMING] Import time: {import_time*1000:.2f}ms", file=sys.stderr)

    argv = argv or sys.argv

    servicer = ProviderServicer(provider)
    stopper = _ShutdownInterceptor()
    server = grpc.server(
        thread_pool=futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[_LoggingInterceptor(), stopper],
    )

    # Give the interceptor a reference to the server so it can stop it
    stopper.server = server

    # Add the Provider service
    rpc.add_ProviderServicer_to_server(servicer, server)

    # Add the GRPCController service required by go-plugin
    class GRPCControllerServicer(controller_rpc.GRPCControllerServicer):
        def Shutdown(self, request, context):
            # Mark as stopped - the interceptor will handle the actual shutdown
            stopper.stopped = True
            return controller_pb.Empty()

    controller_rpc.add_GRPCControllerServicer_to_server(GRPCControllerServicer(), server)

    with tempfile.TemporaryDirectory() as tmp:
        sock_file = f"{tmp}/py-tf-plugin.sock" if "--stable" not in argv else "/tmp/py-tf-plugin.sock"
        tx = f"unix://{sock_file}"

        if "--dev" in argv:
            print("Running in dev mode\n")
            server.add_insecure_port(tx)
            conf = json.dumps(
                {
                    provider.full_name(): {
                        "Protocol": "grpc",
                        "ProtocolVersion": 6,
                        "Pid": os.getpid(),
                        "Test": True,
                        "Addr": {
                            "Network": "unix",
                            "String": sock_file,
                        },
                    },
                }
            )
            print(f"\texport TF_REATTACH_PROVIDERS='{conf}'")

            server.start()
            server.wait_for_termination()
            return

        ssl_start = time.time() if debug_timing else 0.0

        server_chain, server_ssl_config = _self_signed_cert()

        if debug_timing:
            ssl_time = time.time() - ssl_start
            print(f"[TIMING] SSL cert time: {ssl_time*1000:.2f}ms", file=sys.stderr)

        server.add_secure_port(tx, server_ssl_config)

        server.start()

        if debug_timing:
            total_time = time.time() - start_time
            print(f"[TIMING] Total startup time: {total_time*1000:.2f}ms", file=sys.stderr)

        print(
            "|".join(
                [
                    str(1),  # protocol version
                    str(6),  # tf protocol version
                    "unix",  # "tcp",
                    sock_file,  # picked_addr,
                    "grpc",
                    base64.b64encode(server_chain).decode().rstrip("="),
                ]
            )
            + "\n",
            flush=True,
        )

        # This stops an ugly 2s timeout
        # as .stop() does not actually interrupt wait_for_termination
        # There about quite a few termination calls, so longer timeouts
        # quickly add up to the client
        try:
            while server.wait_for_termination(0.05):
                if stopper.stopped:
                    break
        except KeyboardInterrupt:
            # Handle graceful shutdown on Ctrl+C
            server.stop(grace=0.5)


def _get_cert_cache_path() -> Path:
    """Get the path for caching SSL certificates"""
    cache_dir = Path.home() / ".cache" / "tf-python-provider"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "ssl_cert.json"


def _self_signed_cert() -> Tuple[bytes, Any]:
    """Generate or load cached keypair and cert, return a server credentials object"""
    # Lazy load expensive cryptography imports
    import grpc
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    cache_path = _get_cert_cache_path()

    # Try to load from cache first
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)

            # Check if certificate is still valid
            cert_pem = cached["cert_pem"].encode()
            cert = x509.load_pem_x509_certificate(cert_pem)
            # Compare UTC times
            from datetime import timezone as tz

            if cert.not_valid_after_utc > datetime.now(tz.utc):
                # Certificate is still valid, use cached version
                private_key_pem = cached["key_pem"].encode()
                cert_chain = base64.b64decode(cached["cert_chain"])

                return cert_chain, grpc.ssl_server_credentials(
                    private_key_certificate_chain_pairs=[(private_key_pem, cert_pem)],
                    require_client_auth=False,
                )
        except (json.JSONDecodeError, KeyError, ValueError):
            # Cache is corrupted, regenerate
            pass

    # Generate new certificate
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
    now = datetime.now()

    # With subject alternative names
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=1))
        .not_valid_after(now + timedelta(days=7))  # Valid for 7 days instead of 1
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_chain = certificate.public_bytes(serialization.Encoding.DER)
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)

    # Cache the certificate
    try:
        with open(cache_path, "w") as f:
            json.dump(
                {
                    "key_pem": private_key_pem.decode(),
                    "cert_pem": cert_pem.decode(),
                    "cert_chain": base64.b64encode(cert_chain).decode(),
                },
                f,
            )
    except IOError:
        # Failed to cache, but continue anyway
        pass

    return cert_chain, grpc.ssl_server_credentials(
        private_key_certificate_chain_pairs=[
            (
                private_key_pem,
                cert_pem,
            )
        ],
        # root_certificates=client_public_pem,
        require_client_auth=False,
    )


def install_provider(host: str, namespace: str, project: str, version: str, plugin_dir: Path, provider_script: Path):
    """
    Installs the given (host, namespace, project, version) provider into the plugin directory.
    The provider_script should be the terraform-provider-<project> executable.
    If the plugin directory does not exist, it will be created.

    :param host: Host of the provider
    :param namespace: Namespace of the provider
    :param project: Project of the provider
    :param version: Version of the provider
    :param plugin_dir: Directory to install the provider into
    :param provider_script: Path to the provider executable (typically installed as a pip entrypoint)
    """

    executable_name = provider_script.name
    targets = ("darwin_amd64", "darwin_arm64", "linux_amd64", "windows_amd64")

    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "provider.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(provider_script, f"{executable_name}_v{version}")

        hash_value256 = base64.b64encode(hashlib.sha256(provider_script.read_bytes()).digest()).decode()
        module_dir = plugin_dir / f"{host}/{namespace}/{project}"
        module_dir.mkdir(parents=True, exist_ok=True)

        arch_zip_paths = {target: module_dir / f"{executable_name}_{version}_{target}.zip" for target in targets}

        for target_path in arch_zip_paths.values():
            shutil.copy(zip_path, target_path)

        # Update directory manifest
        versions_path = module_dir / "index.json"
        versions = json.loads(versions_path.read_text()) if versions_path.exists() else {}
        versions.setdefault("versions", {})
        versions["versions"][version] = {}
        versions_path.write_text(json.dumps(versions, indent=2, sort_keys=True))

        # Update version manifest
        (module_dir / f"{version}.json").write_text(
            json.dumps(
                {
                    "archives": {
                        target: {
                            "hashes": [f"h1:{hash_value256}"],
                            "url": zip_path.name,
                        }
                        for target, zip_path in arch_zip_paths.items()
                    }
                },
                indent=2,
                sort_keys=True,
            )
        )
