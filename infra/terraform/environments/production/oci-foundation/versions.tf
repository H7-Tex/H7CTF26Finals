terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 7.0"
    }
  }
}

# OCI Resource Manager supplies authentication. Region is the only provider
# field required inside a Resource Manager stack.
provider "oci" {
  region = var.region
}
