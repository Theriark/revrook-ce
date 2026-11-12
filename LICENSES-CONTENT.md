# Content licences

Every dataset under `data/`, and every model under `app/static/models/`, needs one
row here before it can be merged (merge gate check 7). A row gives the exact repository path of the file, where it comes
from, its licence, the date the licence text was read at the source, and the
SHA-256 of the file. `tests/test_content_licences.py` also fails a row whose hash is
not the hash of the committed file. Code dependencies are listed in
`docs/licences.md`.

The datasets of phase 5, part 1 are the control library and two sets of NIST
reference names. The NIST names are credited wherever they are shown (see
`app/checks/reference.py`, `credit_lines`).

The models of the scenes (the offices, road tiles, street lamps and trees of Home's
street and the Evidence Explorer's companies ring) are from three City Kits by Kenney
(www.kenney.nl), CC0 1.0: no credit is required, and it is given here, in `NOTICE` and
in the changelog. Each kit keeps its own `Textures/colormap.png` beside its models, as
the models name it, and its `License.txt`, read on 2026-11-12.

| Path | Source | Licence | Date read | SHA-256 |
| --- | --- | --- | --- | --- |
| data/controls.yaml | revrook own work: the 51 controls of ruleset PC-RULES v0.1, written by us from rnd-report-3 section 3.4. No text of the CIS Controls, the Secure Controls Framework, ISO 27001, the CSA CCM or SIG is embedded; external framework entries are identifiers only, unverified | MIT | 2026-10-18 | 7ced051285354447bb1062288a60a352cc4b8a139496478a40235b3216469857 |
| data/nist/nist-csf-2.0-names.json | NIST OSCAL content, github.com/usnistgov/oscal-content, nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog-min.json at commit 78650f02ad9321bb7b817846f8fbd4f2bcd620de; names of the 32 subcategories the controls map to, unchanged. Credit: NIST Cybersecurity Framework 2.0, National Institute of Standards and Technology (work of the US government, public domain; no endorsement implied) | CC0-1.0 | 2026-10-18 | 02851f8efc44dfcac55f478a5c71a4c1d1fe06552ae42c9c061f74fca4585649 |
| data/nist/nist-sp800-171r3-names.json | NIST OSCAL content, github.com/usnistgov/oscal-content, nist.gov/SP800-171/rev3/json/NIST_SP800-171_rev3_catalog-min.json at commit 78650f02ad9321bb7b817846f8fbd4f2bcd620de; titles of the 26 requirements the controls map to, unchanged. Credit: NIST SP 800-171 Revision 3, National Institute of Standards and Technology (work of the US government, public domain; no endorsement implied) | CC0-1.0 | 2026-10-18 | b8635242d86946863e65228aa93d775c4112d67dfab39cd906e0db88dd74fbed |
| app/static/models/kenney/commercial/building-c.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-c.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | f6887608a95a165503561730252c30506938803731c6546efca12bd47b1666bd |
| app/static/models/kenney/commercial/building-a.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-a.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 5cf220f90ee3f21e7abe38055ca409a48aa8ef1d5ffab6e2deb99e5a5e1ed5e0 |
| app/static/models/kenney/commercial/building-h.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-h.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 6881613ce218bb33a0f56137d4d33b00d307c47e518fbb21ccba1083efbea896 |
| app/static/models/kenney/commercial/building-f.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-f.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 633a25f7fb3ccf98e304a885a36ed900aecee5bde7ecd554729dec753cceea78 |
| app/static/models/kenney/commercial/building-skyscraper-a.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-skyscraper-a.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | d8339bbb75944ff91d1ec9a70ec6dead71bd98b94a42d3dd0fc1f3b107ddbe85 |
| app/static/models/kenney/commercial/building-skyscraper-c.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-skyscraper-c.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | e73c357554f7561fedb8c1cbecf9d7163ba09ada264d661c59a0f0a180e0185f |
| app/static/models/kenney/commercial/building-skyscraper-e.glb | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/building-skyscraper-e.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 21b58a2f2b18d6a7cf8915e8b947bdb6a6a0706da6cffb5a01677c29f03b5935 |
| app/static/models/kenney/commercial/Textures/colormap.png | Kenney (www.kenney.nl), City Kit Commercial 2.1, `Models/GLB format/Textures/colormap.png`, unchanged: the colour texture every model of the kit names | CC0-1.0 | 2026-11-12 | 191bec3889aaaca5018380038fecc129ebb5c2182879a099b7b538b3fa050b5d |
| app/static/models/kenney/commercial/License.txt | Kenney (www.kenney.nl), City Kit Commercial 2.1, `License.txt`, the kit's licence (Creative Commons Zero), its line endings made LF | CC0-1.0 | 2026-11-12 | d59c7328619ce19685cada941e2ed58d849db247c99acd662a184e3c0dad14c0 |
| app/static/models/kenney/roads/road-straight.glb | Kenney (www.kenney.nl), City Kit Roads 2.2, `Models/GLB format/road-straight.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | f8f744fb6fc96dedd5ad1f763b550166f2624a3757bf36b4b39969d2e7cacac5 |
| app/static/models/kenney/roads/road-crossroad.glb | Kenney (www.kenney.nl), City Kit Roads 2.2, `Models/GLB format/road-crossroad.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 2dc52a28cf89ec88025a047c0f6fff4c643f16b0f50f0e9a1140f16230c28b12 |
| app/static/models/kenney/roads/light-square.glb | Kenney (www.kenney.nl), City Kit Roads 2.2, `Models/GLB format/light-square.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 6230d136c8883d7f9bc1b86f0309077e452e26e5e1e587ef1b77abef3c5f047c |
| app/static/models/kenney/roads/Textures/colormap.png | Kenney (www.kenney.nl), City Kit Roads 2.2, `Models/GLB format/Textures/colormap.png`, unchanged: the colour texture every model of the kit names | CC0-1.0 | 2026-11-12 | a48e2962661ae44368ffddf3054f80ed8491d082b757dcc3011184cd9a98b185 |
| app/static/models/kenney/roads/License.txt | Kenney (www.kenney.nl), City Kit Roads 2.2, `License.txt`, the kit's licence (Creative Commons Zero), its line endings made LF | CC0-1.0 | 2026-11-12 | ad241b75fee7fbd0e40f48b8569e3ca065f6ae741a01f1bd9e6472bf5b67dbd5 |
| app/static/models/kenney/suburban/tree-large.glb | Kenney (www.kenney.nl), City Kit Suburban 2.0, `Models/GLB format/tree-large.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 16d1f95c149bc727a953a473cf20bf21de9bf1a88747c4f9d2eeb4ac7d43e291 |
| app/static/models/kenney/suburban/tree-small.glb | Kenney (www.kenney.nl), City Kit Suburban 2.0, `Models/GLB format/tree-small.glb`, unchanged: a model of the scenes (`app/static/js/office.js`) | CC0-1.0 | 2026-11-12 | 5f63359e5f392609d7617cc98070855ca1ffd4f4b4bc3978a5ff56ece88a58d6 |
| app/static/models/kenney/suburban/Textures/colormap.png | Kenney (www.kenney.nl), City Kit Suburban 2.0, `Models/GLB format/Textures/colormap.png`, unchanged: the colour texture every model of the kit names | CC0-1.0 | 2026-11-12 | 9b5de86078c25ef02351a80d35ff3c978693a1044565b73eedd9ae9b5b80665d |
| app/static/models/kenney/suburban/License.txt | Kenney (www.kenney.nl), City Kit Suburban 2.0, `License.txt`, the kit's licence (Creative Commons Zero), its line endings made LF | CC0-1.0 | 2026-11-12 | 2c0cc93bd025107c9a21a188a54935ae0c83cb7e2c0ca3c1dd5b6d15c06116fa |
