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


if __name__ == "__main__":
    unittest.main()
