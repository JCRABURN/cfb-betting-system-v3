# Cross-platform checkout correction

Initial PR55 CI run 44376528416 failed the new original-source custody check on
Linux. The preserved PR53 archive inventory contains Windows CRLF receipt bytes
for 78 code/configuration files. Git stores their LF blobs. Default Linux
checkout therefore differed from the archived bytes, although every character
and all model logic were identical. Local Windows checks had passed.

The attached reconciliation proves each of the 78 original hashes equals its
unchanged Git blob with LF represented as CRLF. Exact-path `text eol=crlf`
attributes now reproduce those original receipt bytes on every platform.
No source file, original hash, expected test result, model or audit output was
modified. The exact-byte custody check remains unchanged and rejects any
content change. This uses the repository's established Week10 receipt pattern.

The original verification-v1 logs remain immutable. Subsequent targeted checks
and final exact-head CI are reported on PR55; the first CI run is not represented
as passing. Rollback is to revert this attributes-and-evidence correction.
