# OCI runtime image capture

This Resource Manager stack captures the four stopped, tested runtime builders as protected custom images. Planning fails unless every builder belongs to the finals compartment and carries the requested role and full source revision.

Feed the resulting `platform-x86` and `platform-arm` OCIDs to the platform stack, and the `production` and `workbench` OCIDs to the fleet stack. Keep this state for the event lifetime; image teardown requires a separate reviewed change that removes the deletion guards.

The failed v0.0.43 builders `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacy3dojy463ubuy7ibn5w5qkl2wuaoclhof7q2k54wof2q`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaccomxx6u2gtj4l75e7rmruf3ygrvp2sqy7e3m3ta6x3ia`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacrkckfhkxhedqym7qggptmctcbcg5wrijqg7xhn6v7drq` and `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacmb2j6gjpf63gphl7xhdc4izh4uakh6nlm5uw2pbwaguq` are prohibited capture inputs even though they were manually stopped.

The failed v0.0.44 builders `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacz5owemazyq72tfqdriutkqsv4k4arluim2mt223sknfq`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacdkqloulenb33an5dw6aj4fro4wbt7dplrt22v43vpyqa`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacf74slght5m37vsh54tdyyfhm2ukebicmx5du2deywo3a` and `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacoy7zvi6n667lc5cru636x3syhzpzuwmrhnlklybla5qa` are also prohibited capture inputs.

The failed v0.0.46 builders `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac3z62q66d7h5qkfxwvnekd6x3scgdaldfyqpbeoklsuaa`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaclkmig5434ou6hkigzf4qx5d3uvbofeiejfoy7fwljc2a`, `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacubaccuijeotibtjqw7zt325dhg4fdw756gntikdnwgoa` and `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacw7aqccrl4vifdxeiyukg3lygu6hnwyqhlrhxtjwwwagq` are also prohibited capture inputs.
