import importlib.machinery
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/libexec/finals-platform/firewall"
LOADER = importlib.machinery.SourceFileLoader("finals_firewall", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("finals_firewall", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class FirewallTests(unittest.TestCase):
    def test_every_role_defaults_all_host_chains_to_drop(self):
        for role in MODULE.ROLES:
            rules = MODULE.render(role)
            self.assertEqual(rules.count("policy drop;"), 3, role)

    def test_repository_management_is_ops_only(self):
        rules = MODULE.render("repository")
        self.assertIn("ip saddr 10.60.200.5 tcp dport 2222 accept", rules)
        self.assertNotIn("ip saddr 10.60.200.5 tcp dport { 22, 2222 } accept", rules)
        self.assertNotIn("10.60.0.0/16 tcp dport 2222", rules)
        self.assertIn("ip saddr 10.60.0.0/16 ct status dnat ct original proto-dst { 22, 443 } accept", rules)

    def test_hills_drop_siblings_and_expose_only_assigned_port(self):
        for role, port in MODULE.HILL_PORTS.items():
            rules = MODULE.render(role)
            self.assertGreaterEqual(rules.count("ip daddr 10.60.210.0/24 counter drop"), 2)
            self.assertIn(f"tcp dport {port} accept", rules)
            for other in set(MODULE.HILL_PORTS.values()) - {port}:
                self.assertNotIn(f"tcp dport {other} accept", rules)

    def test_control_has_no_listener_except_management_ssh(self):
        rules = MODULE.render("control")
        self.assertIn("ip saddr 10.60.200.5 tcp dport 22 accept", rules)
        self.assertNotIn("ct status dnat accept", rules)
        self.assertNotIn("tcp dport 9300 accept", rules)

    def test_mirror_public_egress_requires_explicit_warmup(self):
        offline = MODULE.render("mirror")
        warmup = MODULE.render("mirror", mirror_warmup=True)
        self.assertNotIn("tcp dport { 80, 443 } accept", offline)
        self.assertIn("tcp dport { 80, 443 } accept", warmup)
        self.assertIn("ip daddr 10.60.0.0/16 accept", offline)

    def test_production_orchestrator_has_three_exact_callers(self):
        rules = MODULE.render("production")
        self.assertIn(
            "ip saddr { 10.60.200.10, 10.60.201.20, 10.60.201.30 } tcp dport 9300 accept",
            rules,
        )
        self.assertNotIn("10.60.0.0/16 tcp dport 9300 accept", rules)
        self.assertNotIn("10.60.200.0/24 tcp dport 9300 accept", rules)
        self.assertNotIn("10.60.201.0/24 tcp dport 9300 accept", rules)
        self.assertNotIn("10.60.250.121-10.60.250.135 tcp dport 9300", rules)

    def test_production_service_ingress_has_one_normalized_source(self):
        rules = MODULE.render("production")
        self.assertIn("ip saddr 10.60.250.120 tcp dport 7001-7006 accept", rules)
        self.assertIn(
            "ip saddr 10.60.250.120 ct status dnat ct original proto-dst 7001-7006 accept",
            rules,
        )
        self.assertNotIn("10.60.201.20 tcp dport 7001-7006", rules)
        self.assertNotIn("10.60.250.121-10.60.250.135 tcp dport 7001-7006", rules)

    def test_production_egress_is_limited_to_fixed_dependencies(self):
        rules = MODULE.render("production")
        self.assertIn("ip daddr 10.60.200.10 tcp dport 443 accept", rules)
        self.assertIn("ip daddr 10.60.201.20 tcp dport 9300 accept", rules)
        self.assertIn("ip daddr 10.60.201.30 tcp dport { 22, 443 } accept", rules)
        self.assertIn("ip daddr 10.60.202.10 tcp dport { 3141, 3142, 4873, 5000 } accept", rules)
        self.assertNotIn("tcp dport { 80, 443 } accept", rules)


if __name__ == "__main__":
    unittest.main()
