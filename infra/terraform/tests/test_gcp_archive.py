import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "modules/gcp-archive"


class GCPArchiveTerraformTests(unittest.TestCase):
    def test_archive_identity_is_keyless_and_bound_to_exact_oci_subjects(self):
        source = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.assertIn('workload_identity_pool_provider_id = "oci-instance"', source)
        self.assertIn('"google.subject" = "assertion.subject.dn.cn"', source)
        self.assertIn("var.writer_instance_ids", source)
        self.assertIn("var.verifier_instance_id", source)
        self.assertNotIn("google_service_account_key", source)
        self.assertNotIn("private_key", source)

    def test_writers_can_create_and_verify_but_cannot_mutate_or_delete(self):
        source = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.assertIn('role   = "roles/storage.objectCreator"', source)
        self.assertIn('role   = "roles/storage.objectViewer"', source)
        self.assertNotIn("roles/storage.objectUser", source)
        self.assertNotIn("roles/storage.objectAdmin", source)

    def test_retention_is_at_least_thirty_days_and_not_irreversibly_locked(self):
        main = (MODULE / "main.tf").read_text(encoding="utf-8")
        variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.assertIn("retention_policy", main)
        self.assertIn("is_locked        = false", main)
        self.assertIn("var.retention_seconds >= 2592000", variables)
        self.assertIn("length(certificate) <= 32768", variables)
        self.assertIn("prevent_destroy = true", main)


if __name__ == "__main__":
    unittest.main()
