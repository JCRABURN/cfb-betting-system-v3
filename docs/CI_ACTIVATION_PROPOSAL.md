# CI activation proposal — approval required

The October 29 authenticated REST snapshot proves that repository Actions is
disabled (`GET /actions/permissions`: `enabled: false`). The existing
`Pull Request Tests` workflow, ID 328094886, is active, is present on main,
and already handles pull requests into main. PR-open events for #44 and #45
exist; the repository has zero Actions runs. No workflow duplication or
trigger change is indicated.

Do not apply the following configuration changes without explicit owner approval:

1. Disable these six non-CI workflows through their existing workflow IDs:
   327189312 (Midweek Line Pull), 327189314 (Post-Game Audit),
   339530568 (V3 Managed Database Setup Gate), 337926765
   (V3 Production Operations Gate), 341565576 (V3 Controlled Live-Week
   Shadow Rehearsal), and 327189316 (Weekly CFB Betting Report).
2. Read back all seven workflow states. Require the six above to be
   `disabled_manually` and CI 328094886 to remain `active`.
3. Enable repository Actions with `PUT /actions/permissions`, body
   `{"enabled": true}`. Do not change action allow-lists, token defaults,
   secrets, variables, environments, branch protection, or approval settings.
4. Read back permissions and states. Token defaults must remain read-only;
   automated PR review approval must remain disabled. Stop on a mismatch.
5. Trigger the existing pull-request workflow for the unchanged #44 and #45
   heads using a documented close/reopen PR event, preserving draft state.
   Capture the workflow run URL, head SHA and merge SHA, logs and outcomes.
   No empty commits, manual-dispatch workflow, production activation or merge.

The disabling step prevents repository activation from enabling the already
present scheduled production workflow. It is intentionally fail-closed.
Rollback is to disable repository Actions first and then restore the six
recorded workflow states. Do not restore production workflows while repository
Actions is enabled without separate authorization.

Independent review is a separate gate. The collaborator response lists only
JCRABURN, who authored both PRs. All existing reviews are COMMENTED, not
APPROVED. An independent reviewer's GitHub username and, if necessary, an
owner-managed access grant are required. Do not approve as the owner or add
collaborators without authorization.

Main currently has no branch protection and no repository rulesets. This is
recorded as a governance gap; this proposal does not change those settings or
weaken the owner's required CI/review gates.
