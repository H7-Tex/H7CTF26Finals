# OCI runtime image capture

This Resource Manager stack captures the four stopped, tested runtime builders as protected custom images. Planning fails unless every builder belongs to the finals compartment and carries the requested role and full source revision.

Feed the resulting `platform-x86` and `platform-arm` OCIDs to the platform stack, and the `production` and `workbench` OCIDs to the fleet stack. Keep this state for the event lifetime; image teardown requires a separate reviewed change that removes the deletion guards.

The failed v0.0.43 builders `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacy3dojy463ubuy7ibn5w5qkl2wuaoclhof7q2k54wof2q`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaccomxx6u2gtj4l75e7rmruf3ygrvp2sqy7e3m3ta6x3ia`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacrkckfhkxhedqym7qggptmctcbcg5wrijqg7xhn6v7drq` and `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacmb2j6gjpf63gphl7xhdc4izh4uakh6nlm5uw2pbwaguq` are prohibited capture inputs even though they were manually stopped.
