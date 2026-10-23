# Storage attachment rotation window

This temporary window permits Terraform to move only the existing captures volume attachment from the replaced primary gateway to its reviewed replacement. The four block volumes remain protected and their OCIDs, sizes and contents must not change. Apply only a saved plan whose storage delta replaces the captures attachment and leaves the database, repository and cache attachments unchanged. Restore the attachment guard immediately after the captures mount and event-router readiness checks pass.
