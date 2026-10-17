# Coordinated acceptance refresh

Admin baseline: `dfa33065eeb8be2582ccfb50c7a207f50a838376` in
`Nexa-BE-callback-review`, with a local harness-only dependency override patch.
Client baseline: clean `8871f2b2c01c9da2ce069ad281ac5b1c017edfc2`.

The original harness failed current client site operations with 401 because it
overrode the old persistence dependency but not `get_site_management_client`.
Added that synthetic override for client actors, retaining all race assertions.
This deliberately does not test the gateway/auth boundary; those have separate
real-PocketBase tests. The rerun passed all 24 existing process cases, including
both lock-release recovery cases. UID 1000; lock directory for this run was
`/tmp/opencode/nexa-operation-locks-1000`. No production data or service changes.
The admin HEAD alone does not identify the modified harness; preserve its diff
before claiming immutable final-revision evidence.

Reproduction:

```bash
TMPDIR=/tmp/opencode python3 scripts/acceptance/nexa_process_races.py \
  --admin /home/phantomal/Nexa-BE-callback-review \
  --client /home/phantomal/Nexa-Client-BE-recovery \
  --admin-python /home/phantomal/Nexa-BE/venv/bin/python \
  --client-python /home/phantomal/Nexa-Client-BE/venv/bin/python
```

Hook candidate rerun: 14 checks passed on disposable PocketBase 0.39.0 with a
local HTTP receiver. Artifacts: `/tmp/opencode/nexa-hook-acceptance-xlegl8w7`.
Candidate main hook SHA-256:
`891dedc4f243cdd4d9c5ee85162da49f13ee8288532eb6cfce5f38807dcbad42`.
Hook changes remain uncommitted and undeployed; this rerun does not establish
production-schema, full callback/runner or concurrency acceptance.

Publication update: admin harness patch is now `1b5ffaf`, with the original 24
cases rerun successfully against client `8871f2b`. Hook candidate is `9a812c5`,
Nexa-Pocket PR #3 (draft). Both are published; neither publication is approval.

Added four independent spawned-process cases exercising the actual site/order
decorators against shared synthetic SQLite state: create/mutate versus retention,
with each side winning. Tests assert blocking behind the held site lock and no
write after retention wins. These are lock-boundary tests, not full transaction
HTTP or actual retention-service acceptance. Full client unit suite: 431 passed.

Remaining: review candidates; full order-operation process races (idempotency,
payment/item outcomes and recovery); release-schema/actual backend callback hook
checks; coordinated rule/schema rollout and custom-domain readiness. Keep
#137/#139/#140 open.
