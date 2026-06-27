# Security Policy

## Supported versions

Security fixes are applied to the latest commit on the default branch.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security-sensitive reports.

Instead, open a private security advisory on GitHub (if enabled for this repository) or contact the maintainers directly with:

- A description of the issue
- Steps to reproduce
- Impact assessment (if known)

We aim to acknowledge reports within a reasonable timeframe.

## Secrets and credentials

- Never commit `.env`, API keys, tokens, or private endpoints.
- Use `.env.example` as a template; keep real values in local `.env` only.
- The `outputs/` directory may contain crawled content and run metadata—treat it as local data, not for publication.
- Rotate any API key that may have been exposed in logs, screenshots, or accidental commits.

## Crawling and third-party content

CogniForge fetches user-supplied URLs. Operators are responsible for complying with target sites' terms of service and applicable laws.
