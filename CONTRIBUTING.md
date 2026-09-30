# Contributing To AQA

Thank you for helping improve AQA. Keep each change focused, protect user data,
and describe exactly what you verified.

## Product And Development Model

AQA is distributed as a Tauri desktop application. Each package contains one
target-specific Python runtime, starts the FastAPI backend on loopback, and
loads the built React interface in a native window. Running FastAPI and React
from a source checkout is the main development and automated-test path; it is
not a separately distributed browser product.

See `docs/ARCHITECTURE.md` for the runtime structure. Desktop packages are built
through `packaging/desktop/build_target.sh <target>` on an appropriate native or
properly provisioned build environment. A package is not native-verified merely
because it was cross-built or inspected.

## Supported Development Environment

- Python 3.13
- Node.js 20.19 or later within the 20.x series, with npm
- The recorded Rust toolchain and the platform prerequisites required by Tauri
- macOS, Linux, or Windows

`.python-version` and `.nvmrc` define the repository defaults.

## Set Up The Repository

From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
source .venv/bin/activate
cd frontend
npm ci
cd ../desktop
npm ci
cd ..
```

On Windows, use `.venv\Scripts\python.exe` in place of
`.venv/bin/python`; activate it with `.venv\Scripts\Activate.ps1` in
PowerShell. Keep the environment active for npm API checks and packaging scripts,
which invoke `python` or `python3`.

Optionally install the pre-commit hooks:

```bash
.venv/bin/python -m pre_commit install
```

## Develop And Verify

To run the backend with the built frontend:

```bash
cd frontend
npm run build
cd ..
env -u PYTHONPATH .venv/bin/python -m src.api_server
```

On PowerShell, clear an inherited Python path before starting the server:

```powershell
$env:PYTHONPATH = $null
.venv\Scripts\python.exe -m src.api_server
```

Run checks proportionate to the change. The complete local quality set is:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
env -u PYTHONPATH .venv/bin/python -m pytest -m "not integration" tests
cd frontend
npm run api:check
npm run lint
npm run test:accessibility
npm run format:check
npm run typecheck
npm run coverage
npm run build
```

Browser regressions require Playwright Chromium:

```bash
cd frontend
npm exec playwright install chromium
npm run test:responsive
```

Tests marked `integration` require an explicitly configured, approved
OpenAI-compatible service and do not run in normal CI. Never place credentials,
private endpoints, or research material in commands, fixtures, logs, issues, or
pull requests. Use only synthetic material and follow the test's documented
environment variables.

The checked-in Rust notices record the exact toolchain in
`THIRD_PARTY_LICENSES/RUST_TOOLCHAIN.json` (currently Rust 1.97.1). Use that
toolchain with its `rust-docs` component: packaging checks the compiler identity
and standard-library copyright. If intentionally changing the toolchain,
regenerate the notices with `python packaging/licensing/generate_rust_notices.py`
and review the changes; generation also requires `cargo-about` 0.9.2.

Desktop packages require the target-specific runtime prepared with the existing
`packaging/runtime/` scripts, a Rust toolchain with the matching target, and
Tauri platform prerequisites (Xcode command-line tools on macOS, Microsoft C++
build tools and WebView2 on Windows, or WebKitGTK and distribution packaging
tools on Linux). The shell scripts require Bash, curl, tar, rsync and
SHA-256 tooling;
`build_target.sh` also uses native packaging tools such as `hdiutil` and
`codesign` on macOS. From the repository root, on the matching native platform:

```bash
RUNTIME_PLATFORM=macos-arm64 packaging/runtime/fetch_runtimes.sh
RUNTIME_PLATFORM=macos-arm64 packaging/runtime/install_deps.sh
packaging/desktop/build_target.sh macos-arm64
```

Replace the target with the matching supported operating system and processor.
Runtime/model caches are optional downloads, not source prerequisites. Package
builds need network access for missing pinned runtime and dependency inputs.

AQA is experimental research software. Updates and responses to reports or
contributions cannot be guaranteed. Use the contact listed in [README.md](README.md)
for reports; follow [SECURITY.md](SECURITY.md) for vulnerabilities.

## Change Rules

- Keep changes small and cohesive. Do not combine a bug fix, unrelated
  refactoring, and file cleanup in one change.
- Read the relevant implementation and tests before editing. Keep schemas,
  generated API contracts, prompt assets, persisted keys, user-facing labels,
  tests, and shipped assets synchronized when a contract changes.
- Add or update focused tests for changed behavior. Do not run unrelated full
  suites or rebuild unaffected packages merely because a file changed.
- Follow `docs/ACCESSIBILITY.md` and `docs/DESIGN_SYSTEM.md` for UI changes.
  Inspect the rendered gallery and representative desktop and narrow layouts in
  both interface languages when applicable.
- Never read, commit, or distribute `.env`, `data/settings.json`, `.aqa/`,
  legacy `.aqa_workbench/`, saved conversations, models, logs, or other local
  application data. Use isolated synthetic profiles for tests.
- Add notable user-visible or release-relevant changes under `Unreleased` in
  `CHANGELOG.md`. Use only the applicable Keep a Changelog categories, make
  breaking or security impact prominent, and omit routine internal churn.
- At release, assign the accumulated changelog entry its actual Semantic
  Versioning version and `YYYY-MM-DD` release date, then create a new empty
  `Unreleased` section above it. Add tag and comparison links only when those
  destinations exist.
- Create one focused commit for completed, verified implementation work unless
  a maintainer asks otherwise. Stage only files belonging to the change and
  inspect the complete staged diff. This commit rule is independent of whether
  a changelog entry is warranted.

## Verification Evidence

Automated, browser, source, simulated-provider, live-provider, package
inspection, cross-build, packaged-native, and screen-reader checks are different
evidence classes. Report only what was actually exercised. Native GUI evidence
requires observing the behavior in a fresh packaged Tauri application using a
disposable `AQA_DESKTOP_DATA_DIR` and a confirmed app/backend process pair.

## Pull Request Checklist

- [ ] The change and its motivation are clearly described.
- [ ] The change is focused, and unrelated files are excluded.
- [ ] Relevant tests were added or updated and run locally.
- [ ] UI changes follow the accessibility and design-system guidance; keyboard,
      focus, semantics, announcements, contrast, reflow, motion, and both
      interface languages were checked as applicable.
- [ ] Relevant Ruff, frontend lint, typecheck, tests, and build checks pass.
- [ ] No credentials, personal data, local state, or generated build artifacts
      are included.
- [ ] The changelog and documentation are updated when warranted.
- [ ] Platform and verification claims name the evidence class and disclose
      known gaps.
