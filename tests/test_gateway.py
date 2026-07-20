import urllib.parse
import unittest

import gateway


class GatewayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        gateway.buckets.clear()

    def test_allowlists_formatted_cnq_process_route():
        self.assertTrue(
            gateway.is_datajud_process_path(
                "/v1/datajud/processos/0000000-00.0000.0.00.0000"
            )
        )

    def test_allowlists_timeline_route():
        self.assertTrue(
            gateway.is_datajud_process_path(
                "/v1/datajud/processos/0000000-00.0000.0.00.0000/timeline"
            )
        )

    def test_rejects_path_traversal():
        self.assertFalse(
            gateway.is_datajud_process_path(
                "/v1/datajud/processos/../../health"
            )
        )

    def test_rejects_arbitrary_text_path():
        self.assertFalse(
            gateway.is_datajud_process_path(
                "/v1/datajud/processos/teste"
            )
        )

    def test_build_proxy_target_preserves_query_only():
        parsed = urllib.parse.urlparse(
            "https://example.invalid/v1/datajud/health?tribunal=tjsc#fragment"
        )
        self.assertEqual(
            gateway.build_proxy_target(parsed),
            "/v1/datajud/health?tribunal=tjsc",
        )

    def test_rate_limit_rejects_after_capacity():
        first = gateway.allow("test", 1, 60)
        second = gateway.allow("test", 1, 60)

        self.assertTrue(first[0])
        self.assertFalse(second[0])
        self.assertGreaterEqual(second[2], 1)


if __name__ == "__main__":
    unittest.main()
