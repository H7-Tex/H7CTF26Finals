# Gateway rotation window

This temporary window permits replacement of only the primary and standby gateways and their secondary private-IP bindings with the corrected fixed cloud-init that brings SSH up before recipient and secret commissioning.

The two reserved public addresses remain protected in the separate addresses stack. They must be unassigned before replacement, retain their exact OCIDs and values, and be reassigned only to the verified `web` and `vpn` private-IP resources. The protected captures volume remains unchanged while its attachment later moves to the replacement primary. The saved plans must contain no public-address, network, platform, fleet, volume or backup destruction. Restore every gateway, private-IP and attachment guard immediately after both replacements pass boot, recipient and commissioning checks.
