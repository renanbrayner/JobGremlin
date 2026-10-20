# Local configuration

This directory belongs to the parallel workspace. Copies of personal
configuration may live here, but they are gitignored:

- `profile.yml`
- `cv-facts.json`
- `answers*.json`
- `career-ops.env`

When a file is absent, the copied flow scripts read it from
`$CAREER_OPS_UPSTREAM/config/`. The upstream checkout is never written to.

`career-ops-reply` merges answers into `config/answers-hermes.json` here (or the
path in `CAREER_OPS_ANSWERS`, which must stay inside the workspace), so a parked
form can be resumed without editing the read-only upstream copy.

Start from the example:

```bash
cp config/career-ops.env.example config/career-ops.env
```
