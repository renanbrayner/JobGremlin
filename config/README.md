# Local configuration

This directory belongs to the parallel workspace. Copies of personal
configuration may live here, but they are gitignored:

- `profile.yml`
- `cv-facts.json`
- `answers*.json`
- `career-ops.env`

When a file is absent, the copied flow scripts read it from
`$CAREER_OPS_UPSTREAM/config/`. The upstream checkout is never written to.

Start from the example:

```bash
cp config/career-ops.env.example config/career-ops.env
```
