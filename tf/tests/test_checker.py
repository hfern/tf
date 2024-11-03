from unittest import TestCase

from tf.checker import check_attributes
from tf.schema import Attribute
from tf.types import String
from tf.utils import Diagnostics


class CheckAttributeTest(TestCase):
    def check_error_case(self, attr) -> Diagnostics:
        diags = Diagnostics()
        check_attributes(diags, [attr])
        self.assertTrue(diags.has_errors())
        return diags

    def test_optional_and_required(self):
        diags = self.check_error_case(Attribute("aname", String(), optional=True, required=True))
        self.assertIn("Optionality cannot be set if required", str(diags))

    def test_not_optional_not_required_not_computed(self):
        diags = self.check_error_case(Attribute("aname", String()))
        self.assertIn("Optionality must be set if required omitted and not computed", str(diags))

    def test_required_and_optional(self):
        diags = self.check_error_case(Attribute("aname", String(), required=True, optional=True))
        self.assertIn("Required cannot be set if optional", str(diags))

    def test_required_and_computed(self):
        diags = self.check_error_case(Attribute("aname", String(), required=True, computed=True))
        self.assertIn("Required cannot be set if computed", str(diags))

    def test_not_required_not_optional_not_computed(self):
        diags = self.check_error_case(Attribute("aname", String()))
        self.assertIn("Optionality must be set if required omitted and not computed", str(diags))

    def test_computed_and_required(self):
        diags = self.check_error_case(Attribute("aname", String(), computed=True, required=True))
        self.assertIn("Computed cannot be set if required", str(diags))

    def test_computed_and_default(self):
        diags = self.check_error_case(Attribute("aname", String(), optional=True, default="default"))
        self.assertIn("You cannot set a default value if computed is not also set", str(diags))
