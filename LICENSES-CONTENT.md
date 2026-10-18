# Content licences

Every dataset under `data/` needs one row here before it can be merged (merge
gate check 7). A row gives the exact repository path of the file, where it comes
from, its licence, the date the licence text was read at the source, and the
SHA-256 of the file. `tests/test_content_licences.py` also fails a row whose hash is
not the hash of the committed file. Code dependencies are listed in
`docs/licences.md`.

The datasets of phase 5, part 1 are the control library and two sets of NIST
reference names. The NIST names are credited wherever they are shown (see
`app/checks/reference.py`, `credit_lines`).

| Path | Source | Licence | Date read | SHA-256 |
| --- | --- | --- | --- | --- |
| data/controls.yaml | revrook own work: the 51 controls of ruleset PC-RULES v0.1, written by us from rnd-report-3 section 3.4. No text of the CIS Controls, the Secure Controls Framework, ISO 27001, the CSA CCM or SIG is embedded; external framework entries are identifiers only, unverified | MIT | 2026-10-18 | a72fdf2126d92192a4dd658fb460925eb48f7fc95e7ed8d792a8a6fbbef65190 |
| data/nist/nist-csf-2.0-names.json | NIST OSCAL content, github.com/usnistgov/oscal-content, nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog-min.json at commit 78650f02ad9321bb7b817846f8fbd4f2bcd620de; names of the 32 subcategories the controls map to, unchanged. Credit: NIST Cybersecurity Framework 2.0, National Institute of Standards and Technology (work of the US government, public domain; no endorsement implied) | CC0-1.0 | 2026-10-18 | 02851f8efc44dfcac55f478a5c71a4c1d1fe06552ae42c9c061f74fca4585649 |
| data/nist/nist-sp800-171r3-names.json | NIST OSCAL content, github.com/usnistgov/oscal-content, nist.gov/SP800-171/rev3/json/NIST_SP800-171_rev3_catalog-min.json at commit 78650f02ad9321bb7b817846f8fbd4f2bcd620de; titles of the 26 requirements the controls map to, unchanged. Credit: NIST SP 800-171 Revision 3, National Institute of Standards and Technology (work of the US government, public domain; no endorsement implied) | CC0-1.0 | 2026-10-18 | b8635242d86946863e65228aa93d775c4112d67dfab39cd906e0db88dd74fbed |
