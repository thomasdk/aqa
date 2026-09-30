# Security Policy

## Supported version

Reports should identify the affected source commit or desktop version. AQA is
experimental research software; updates, fixes, and response times cannot be
guaranteed.

## Reporting a vulnerability

Do not disclose security problems in a public issue or public chat. Email
[sebastian.bornschlegl@sowi.uni-stuttgart.de](mailto:sebastian.bornschlegl@sowi.uni-stuttgart.de)
privately and include:

- the affected version or commit ID,
- reproducible steps,
- the expected and observed impact,
- where safe, a minimal proof using synthetic data instead of real research
  data or credentials.

Until the project owner responds, do not publish details that would make the
problem easier to exploit.

## Confidential data

Reports and diagnostic archives must not contain content from:

- `.env`
- `data/settings.json`
- `.aqa/` and legacy `.aqa_workbench/`
- `conversations/`
- `logs/`

Replace API keys, private host addresses, research material, and saved
discussions with synthetic examples. Desktop staging uses an explicit
source/data allowlist and audits the exclusion of local state.
