# Contributing

Describe the user-visible problem, your proposed behavior and relevant checks.
Keep changes focused. Read [the product overview](README.md) and
[documentation index](docs/README.md) before changing behavior.

- Keep the frontend vanilla HTML/CSS/JavaScript, use existing design tokens,
  support both themes, and include desktop/mobile screenshots for UI changes.
- Preserve current session revocation, CSRF/origin checks, queue ownership and
  submission-feedback rules. Add regression coverage for changed boundaries.
- Use [problem authoring](docs/making-problems.md) and
  [solution authoring](docs/making-solutions.md) for content proposals. Private
  tests, reference packages and production configuration do not belong in Git.
- Follow [.github/workflows/ci.yml](.github/workflows/ci.yml) for checks.
  Public clones lack private problem packages; report skips and environment
  limits honestly. macOS tests do not qualify Linux sandbox isolation.
- Prepare additive, idempotent SQL for maintainer review. Do not test changes on
  the live database or send email/load against production without authorization.

Report a suspected vulnerability privately to
[newbiegrader.team@gmail.com](mailto:newbiegrader.team@gmail.com), with a minimal
reproduction and impact. Do not post credentials, personal data or private test
bytes in a public issue.
