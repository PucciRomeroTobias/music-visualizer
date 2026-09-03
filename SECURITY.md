# Security policy

## Supported version

Security fixes are applied to the latest commit on `main`. There are no supported release branches yet.

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** option in the repository's Security tab. Do not open a public issue with exploit details, credentials, or personal data.

Include the affected component, reproduction steps, impact, and any suggested mitigation. You should receive an initial response within seven days.

## Sensitive local data

The collection pipeline can use third-party API credentials and stores source metadata in SQLite. Keep `.env`, `data/`, browser cookies, OAuth tokens, and generated exports out of commits. The SoundCloud collector uses an unofficial API and a user-provided OAuth token; use a dedicated, least-privilege account and review SoundCloud's current terms before running it.
