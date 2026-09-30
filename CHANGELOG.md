# Changelog

All notable changes to AQA will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This section is the draft for AQA's initial public release. A version and release
date will be assigned only when that release is made.

### Added

- Research-led sessions for exploring source material or critiquing an
  interpretation while keeping the source distinct from generated contributions.
- Configurable analytical perspectives, multi-round follow-up questions,
  researcher notes, references, Quick Actions, and optional synthesis.
- Transparent prompt configuration and preview for perspectives, session types,
  global prompt blocks, and the assembled instruction structure.
- Automatically saved sessions that can be reopened, continued, renamed,
  favourited, and exported as Markdown.
- Integrated AI for supported local models and External AI for
  OpenAI-compatible services, including services running locally.
- English and German interfaces, adaptive light and dark appearances, and
  keyboard-accessible desktop workflows.
- Desktop settings for notifications, language, appearance, and preventing idle
  sleep while a generation is running.

### Changed

- **Required action for users of internal pre-release builds:** AQA uses a new
  application identity and data directory. Data from earlier AQA Workbench
  builds is left in place and is not imported automatically. Export anything
  needed from the earlier build before moving or removing its data.

### Security

- Bind the source-development frontend server to loopback by default to reduce
  exposure of development files to other machines.
- Update affected transitive API-generation, build and test dependencies within
  their compatible version ranges.
- Upgrade the coordinated frontend development and test toolchain to fix the
  remaining Vite, Vitest mocker/API, and esbuild development-server advisories.

### Technical Notes

- AQA is distributed as a Tauri desktop application containing one
  target-specific Python runtime. The embedded FastAPI backend serves the built
  React interface to the native window; there is no separate portable web
  distribution.
- Integrated AI runs generation on the device, but setup or repair can download
  runtime files from GitHub and model files from Hugging Face. External AI sends
  the assembled prompt and eligible discussion context to the service configured
  by the user.
- The initial public packages are expected to lack trusted publisher signing.
  Verify the package filename and checksum through the official release channel
  and follow the repository's installation guidance before opening a package.
- AQA is experimental research software. Generated contributions require
  critical review and do not replace methodological judgement.
