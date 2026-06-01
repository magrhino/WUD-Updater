## Summary

Start with 1-3 sentences that explain the objective, user-visible problem, failure fixed, or maintenance goal. Explain why this PR exists before listing implementation changes.

Then add concise bullets for the concrete changes, touched areas, operational impact, and anything reviewers should pay special attention to.

- <implementation detail>

## Scope

- [ ] This PR has one reviewable objective
- [ ] Follow-up work, stacked PRs, or intentionally deferred changes are called out here:

## Checklist

- [ ] Tests added or updated
- [ ] `README.md` or `docs/` updated if install, deployment, config, or user-facing behavior changed
- [ ] `docs/examples/template.env` or `docs/examples/webui.env.example` updated if environment variables or example config changed
- [ ] Release Please/changelog impact considered; no manual `CHANGELOG.md` edit needed outside release prep

## Test plan

Mark only checks that actually ran. For skipped or not-applicable checks, leave the box unchecked and add `N/A - reason`.

- [ ] `tests/run-all.sh`
- [ ] Focused test(s):
    - `Test 1` 
    - `Test 2`

- [ ] Docker or Compose validation, if container behavior changed:
