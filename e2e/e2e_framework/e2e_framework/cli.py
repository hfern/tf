import argparse
import io
import os
import platform
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import requests

DEFAULT_TF_PACKAGE = "opentofu@v1.10.5"


def main():
    handlers = {
        "install": cmd_install,
        "run": cmd_run,
    }

    parser = argparse.ArgumentParser(description="TF e2e tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    install_parser = subparsers.add_parser("install", help="Install OpenTofu into test environment")
    install_parser.add_argument("package_name", help="Version to install eg: opentofu@v1.2.3")

    run_parser = subparsers.add_parser("run", help="Run tests")
    run_parser.add_argument("--tf", dest="package_name", help="Version to run against eg: opentofu@v1.2.3")
    run_parser.add_argument("tests", nargs="*", help="Test modules, classes or methods to run (default: cwd)")
    run_parser.add_argument("-v", action="count", default=1, help="Verbosity level")

    matches = parser.parse_args(sys.argv[1:])
    handlers[matches.command](matches)


def cmd_run(args: argparse.Namespace):
    binary = tf_package_to_binary(args.package_name or DEFAULT_TF_PACKAGE)

    if not binary.exists():
        print("Error: OpenTofu binary not installed! Please run 'install' command first.", file=sys.stderr)
        sys.exit(1)

    if args.tests:
        tests = unittest.defaultTestLoader.loadTestsFromNames(args.tests)
    else:
        tests = unittest.defaultTestLoader.discover(
            start_dir=os.getcwd(),
            pattern="test_*.py",
        )

    os.environ["TF_BINARY_NAME"] = str(binary)

    runner = unittest.TextTestRunner(verbosity=args.v)
    result = runner.run(tests)

    if not result.wasSuccessful():
        sys.exit(1)


def tf_package_to_binary(package: str) -> Path:
    if not package.startswith("opentofu@"):
        print("Error: package name must start with 'opentofu@' -- only OpenTofu is supported", file=sys.stderr)
        sys.exit(1)

    version = package.split("@", 1)[1]
    binary_name = f"tofu-{version}"
    return Path(sys.executable).parent / binary_name


def cmd_install(args: argparse.Namespace):
    package = args.package_name
    destination_path = tf_package_to_binary(package)

    if destination_path.exists():
        print(f"OpenTofu package {package} is already installed into the venv!")
        return

    plat = sys.platform.lower()
    arch = {"x86_64": "amd64"}.get(platform.machine().lower(), platform.machine().lower())

    version = package.split("@", 1)[1]
    zip_name = f"tofu_{version.lstrip('v')}_{plat}_{arch}.zip"

    print(f"Fetching release {version}...")
    release = get_tofu_release(version)

    assets = [a for a in release["assets"] if a["name"] == zip_name]

    if not assets:
        print(f"Error: No release asset found for {zip_name}", file=sys.stderr)
        sys.exit(1)

    asset = assets[0]

    print(f"Downloading {zip_name}...")

    zip_request = requests.get(asset["browser_download_url"])
    if zip_request.status_code != 200:
        print(
            f"Error: Failed to download asset {zip_name}: {zip_request.status_code} {zip_request.text}", file=sys.stderr
        )
        sys.exit(1)

    zip_contents = io.BytesIO(zip_request.content)
    with zipfile.ZipFile(zip_contents) as zf:
        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extract("tofu", path=tmpdir)
            shutil.move(f"{tmpdir}/tofu", destination_path)
            destination_path.chmod(0o755)

    print(f"Installed OpenTofu {version} to {destination_path}")


def get_tofu_release(tag) -> dict:
    """
    curl -L \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <YOUR-TOKEN>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/OWNER/REPO/releases/tags/TAG
    """

    release = requests.get(
        f"https://api.github.com/repos/opentofu/opentofu/releases/tags/{tag}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    if release.status_code != 200:
        raise ValueError(f"Failed to get release info for tag {tag}: {release.status_code} {release.text}")

    return release.json()
