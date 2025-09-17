from unittest import TestCase

import responses
from myprovider import DnsResolver, MyProvider

from tf.iface import ReadDataContext
from tf.utils import Diagnostics, Unknown


class TestDnsResolver(TestCase):
    def setUp(self):
        super().setUp()

        self.responses = responses.RequestsMock()
        self.responses.start()
        self.addCleanup(self.responses.stop)
        self.addCleanup(self.responses.reset)

        self.provider = MyProvider()

    def test_happy(self):
        self.responses.add(
            responses.GET,
            "https://dns.google/resolve?name=example.com&type=A",
            json={
                "Answer": [
                    {"data": "1.2.3.4", "TTL": 123},
                ]
            },
        )

        dns_ds: DnsResolver = self.provider.new_data_source(DnsResolver)
        context = ReadDataContext(Diagnostics(), self.provider.get_model_prefix() + dns_ds.get_name())

        state = dns_ds.read(
            context,
            {
                "hostname": "example.com",
                "type": "A",
                "data": Unknown,
                "ttl": Unknown,
            },
        )

        self.assertFalse(context.diagnostics.has_errors())
        self.assertEqual(
            {
                "hostname": "example.com",
                "type": "A",
                "data": "1.2.3.4",
                "ttl": 123,
            },
            state,
        )

    def test_no_records(self):
        self.responses.add(
            responses.GET,
            "https://dns.google/resolve?name=example.com&type=A",
            json={},
        )

        dns_ds = self.provider.new_data_source(DnsResolver)
        context = ReadDataContext(Diagnostics(), self.provider.get_model_prefix() + dns_ds.get_name())

        state = dns_ds.read(
            context,
            {
                "hostname": "example.com",
                "type": "A",
                "data": Unknown,
                "ttl": Unknown,
            },
        )

        self.assertIsNone(state)
        self.assertTrue(context.diagnostics.has_errors())
        self.assertEqual(1, len(context.diagnostics.errors))
        self.assertEqual("No DNS records found", context.diagnostics.errors[0].summary)
        self.assertEqual("No A records found for example.com", context.diagnostics.errors[0].detail)
        self.assertEqual(["hostname"], context.diagnostics.errors[0].path)
