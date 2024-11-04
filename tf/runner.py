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
from typing import Optional, Tuple

import grpc
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tf.gen import tfplugin_pb2_grpc as rpc
from tf.iface import Provider
from tf.provider import ProviderServicer


class _LoggingInterceptor(grpc.ServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        print(f"Handling call to {handler_call_details}")
        return continuation(handler_call_details)


class _ShutdownInterceptor(grpc.ServerInterceptor):
    def __init__(self):
        self.stopped = False

    def intercept_service(self, continuation, handler_call_details):
        if handler_call_details.method == "/plugin.GRPCController/Shutdown":
            self.stopped = True

        return continuation(handler_call_details)


def run_provider(provider: Provider, argv: Optional[list[str]] = None):
    """
    Run the given provider with the given arguments.

    :param provider: Provider instance to run
    :param argv: Optional arguments to run the provider with
    """

    argv = argv or sys.argv

    servicer = ProviderServicer(provider)
    stopper = _ShutdownInterceptor()
    server = grpc.server(
        thread_pool=futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[_LoggingInterceptor(), stopper],
    )

    rpc.add_ProviderServicer_to_server(servicer, server)

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

        server_chain, server_ssl_config = _self_signed_cert()
        server.add_secure_port(tx, server_ssl_config)

        server.start()

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
        while server.wait_for_termination(0.05):
            if stopper.stopped:
                print("Stopping server...")
                break


def _self_signed_cert() -> Tuple[bytes, grpc.ServerCredentials]:
    """Generate a keypair, a cert, and return a server credentials object"""
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
        .not_valid_after(now + timedelta(days=1))
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

    return cert_chain, grpc.ssl_server_credentials(
        private_key_certificate_chain_pairs=[
            (
                private_key_pem,
                certificate.public_bytes(serialization.Encoding.PEM),
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
