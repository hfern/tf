import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Optional, Sequence
from unittest import TestCase


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


class ProviderTest(TestCase):
    PROVIDER_NAME = ""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(tmp.name)
        self.addCleanup(tmp.cleanup)
        self.rc_file = self.tmp / ".tf.rc"

    def _get_tf_command(self):
        return os.environ.get("TF_BINARY_NAME", "tofu")

    def run_test(self, hcl: str, expect_error: bool = False, error_message: str = ""):
        tf_file = self.tmp / "main.tf"
        tf_file.write_text(hcl)

    def _tf_run(
        self, command: Sequence[str], hcl: str, expect_error=False, expect_in_output: Optional[Sequence[str]] = None
    ) -> Result:
        (self.tmp / "main.tf").write_text(hcl)
        self._auto_install_rc()

        (self.tmp / "version.tf").write_text(
            dedent(
                """\
            terraform {
              required_providers {
                %s = {
                  source  = "%s"
                }
              }
            }
        """
                % (
                    self.PROVIDER_NAME.split("/")[-1],
                    self.PROVIDER_NAME,
                )
            )
        )

        env = {
            "TF_CLI_CONFIG_FILE": str(self.rc_file),
            "TF_CLI_ARGS": "-no-color",
        }

        invoke_args = [self._get_tf_command()] + list(command)

        process = subprocess.Popen(
            invoke_args,
            cwd=self.tmp,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        stdout, stderr = process.communicate()
        res = Result(
            returncode=process.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

        if expect_error:
            self.assertNotEqual(res.returncode, 0)
        else:
            self.assertEqual(res.returncode, 0, msg=res.stderr)

        for s in expect_in_output or []:
            self.assertIn(s, res.stdout + res.stderr)

        return res

    def tf_plan(self, hcl: str, expect_error=False, expect_in_output: Optional[Sequence[str]] = None) -> Result:
        return self._tf_run(["plan"], hcl=hcl, expect_error=expect_error, expect_in_output=expect_in_output)

    def tf_apply(self, hcl: str, expect_error=False, expect_in_output: Optional[Sequence[str]] = None) -> Result:
        return self._tf_run(
            ["apply", "-auto-approve"], hcl=hcl, expect_error=expect_error, expect_in_output=expect_in_output
        )

    def _auto_install_rc(self):
        if not self.rc_file.exists():
            self.rc_file.write_text(
                dedent(
                    """\
                provider_installation {
                  dev_overrides {
                      "%s" = "%s"
                  }
                  direct {}
                }
            """
                    % (self.PROVIDER_NAME, str(Path(sys.executable).parent))
                )
            )

    def tf_state(self) -> dict:
        process = subprocess.Popen(
            [self._get_tf_command(), "show", "-json"],
            cwd=self.tmp,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"TF_CLI_CONFIG_FILE": str(self.rc_file), "TF_CLI_ARGS": "-no-color"},
        )
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, msg=stderr.decode())
        import json

        return json.loads(stdout.decode())
