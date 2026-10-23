# Gateway rotation window

This temporary window permits the reviewed replacement of the primary and standby gateways and their secondary private-IP bindings with the sealed gateway image and dedicated operations-relay key.

The two reserved public addresses remain protected in the separate addresses stack. They must be unassigned before this window, retain their exact OCIDs and values throughout it, and be reassigned only to the newly verified `web` and `vpn` private-IP resources. The protected captures volume remains unchanged while only its attachment moves to the replacement primary gateway. The saved plans must contain no public-address, network, platform, fleet, volume or backup destruction. Restore every gateway, private-IP and volume-attachment lifecycle guard immediately after both replacement hosts pass boot and recipient verification.
