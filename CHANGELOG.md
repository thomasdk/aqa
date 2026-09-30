# Changelog

## [Unreleased]

## [1.0.0] - 2026-09-30

### Added

- Initial release of AQA as a desktop application for qualitative research.

### Changed

- **Required action for users of internal pre-release builds:** AQA uses a new application identity and data directory. Data from earlier AQA Workbench builds is left in place and is not imported automatically. Export anything needed from the earlier build before moving or removing its data.

### Security

- The initial public packages are expected to lack trusted publisher signing. Verify the package filename and checksum through the official release channel and follow the repository's installation guidance before opening a package.
