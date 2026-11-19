# Closed evidence inventory for integration with Week 12

The original v1 generator discovered every file in outputs at replay time. That
would silently broaden the audit's evidence inventory when a later week was
added, although no original grade changed. Replay v2 verifies the exact original
input list from the SHA-pinned v1 manifest. Every original input and every v1
output remains byte-checked; changed or missing evidence fails. New unrelated
weekly artifacts cannot become historical audit evidence.

The original v1 directory, workbook and context-v2 are unchanged. v1's original
generator remains reproducible at commit
936352866a21a7b535c9728df7e6a8e979b3f1af. v2 records the revised generator hash and
the original manifest hash. All 56 non-manifest audit artifacts must be exactly
identical between v1 and v2; the comparison is recorded alongside this note.
The default audit verifier now checks v2 and the preserved v1 inventory.

Three adversarial tests reject original evidence/manifest corruption and prove
that the inventory does not scan future output directories. No policy, forecast,
grade, research result, workbook cell or prior custody timestamp changes.
Rollback is to revert this replay implementation commit; keep all v1 evidence.
