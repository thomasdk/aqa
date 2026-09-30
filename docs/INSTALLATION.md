# Installation and First Use

AQA is experimental research software. Packages lack trusted publisher signing. Obtain packages and their checksums from the project, and verify the package filename and SHA-256 checksum before opening a package. Updates and responses to reports cannot be guaranteed.

## Choose the correct package

- **macOS:** use the `.dmg` matching Apple silicon or Intel.
- **Windows:** use the x64 installer for most Windows 10/11 PCs. Use ARM64 only on Windows 11 devices that report an ARM-based processor.
- **Linux:** use the `.deb` on Debian 12 or Ubuntu 22.04 and later, or the `.AppImage` on a compatible distribution.

## Install

The operating-system links below describe app-specific opening procedures.

### macOS

Open the disk image and drag AQA to Applications. Because the package lacks trusted publisher signing, macOS may block the first launch. Try to open the app once, then open **System Settings → Privacy & Security**, select **Open Anyway** for AQA, confirm **Open**, and authenticate if requested. Apple documents this app-specific exception in [Safely open apps on your Mac](https://support.apple.com/en-gb/102445). The option may be unavailable on managed devices; do not weaken system-wide security settings.

### Windows

Your browser may first warn about downloading an uncommon executable. That download warning is separate from the Windows SmartScreen dialog shown when an app starts. Do not continue if either warning reports malware or a changed/tampered file. For the ordinary unsigned-app launch dialog **Windows protected your PC**, and only when the package and matching checksum came from the project, use **More info → Run anyway** if those options are available. If Windows Defender Smart App Control or an organisation policy blocks the app, there may be no per-app bypass; ask the device administrator rather than disabling protection. Microsoft explains [reputation-based protection](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation), [Smart App Control](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions), and [administrator-managed SmartScreen settings](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/available-settings).

### Linux

Install the `.deb` with the distribution’s package installer. For an `.AppImage`, mark the file executable and launch it. Desktop integration varies by distribution; a warning from the local security policy should be resolved with the administrator rather than bypassed globally.

## First use

1. **Prepare** opens with the selected New Leipzig Charter material as a **Text Document**; replace it with your own material when ready.
2. Select the session type, enter the target language, and write an exploration question.
3. Under **Configure**, choose **Integrated AI** or configure an institutionally approved **External AI** endpoint.
4. Return to **Prepare** and start the discussion.
5. In **Discuss**, read the perspectives as suggestions, not findings. Add notes or references where they help your own analysis, then continue with one focused follow-up.
6. Use **Stop Generation** when needed. Contributions that already finished remain available.
7. Close and reopen AQA. Use **Continue** to reopen the automatically saved session, then use **Export** to save a Markdown copy at a location you choose.

Use a focused excerpt on slow hardware to reduce generation time; retain its source attribution.

## Data and network boundaries

Integrated generation runs on the device, but initial setup or repair can download runtime files from GitHub and model files from Hugging Face. External AI sends the assembled prompt—including material, research instructions, target language, selected notes/references, and eligible prior discussion—to the configured host. Do not use confidential material with a host unless its processing terms and your institutional approvals permit it.

Mutable data is stored per user:

- macOS: `~/Library/Application Support/AQA`
- Windows: `%LOCALAPPDATA%\AQA`
- Linux: `$XDG_DATA_HOME/aqa`, or `~/.local/share/aqa`

This directory can contain settings, locally stored API keys, sessions, prompt customisations, logs, and Integrated-AI files. Ordinary uninstallation is not expected to remove it; that is a source-level assessment, not a native observation on every platform. To remove research data, first export anything required, close AQA, uninstall it, and then remove only the matching application-data directory under your own user account. Do not delete a broader parent directory.

## Current limitations

- Packages lack trusted publisher signing or notarisation. Native verification coverage varies by operating system and processor; consult the evidence provided with the specific package.
- AI output may be inaccurate, reductive, or inconsistent. Researchers remain responsible for source comparison, interpretation, and documentation.
- API keys are stored in the local settings file rather than an operating-system keychain.
- Replacing or removing the application does not by itself prove that copied exports, backups, repository history, or older packages no longer contain data.
