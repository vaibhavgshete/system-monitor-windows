# Code signing (SignPath Foundation)

Windows **Smart App Control** blocks unsigned programs outright: there's no "Run anyway" button.
SmartScreen also warns about them. Signing the exe with a trusted certificate fixes both.
[SignPath Foundation](https://signpath.org/) signs open-source projects for free, using
their certificate. Builds must come from the public source on GitHub Actions, which is what
`.github/workflows/release.yml` does.

## 1. Apply (one time)

Apply at https://signpath.org/ ("Apply for free code signing"). Have these ready:

| Field | Value |
|---|---|
| Project | System Monitor for Windows |
| Repository | https://github.com/vaibhavgshete/system-monitor-windows |
| License | MIT (OSI-approved) |
| Build system | GitHub Actions, workflow `.github/workflows/release.yml` |
| Files to sign | `SystemMonitor-portable.exe` and `SystemMonitor/SystemMonitor.exe` (in the uploaded artifact) |
| What it does | Task Manager alternative: shows processes and resource usage, no network access |
| Code signing policy | README section "Code signing policy" |

SignPath reviews the application, so expect it to take some time. Their requirements can change,
so read the current terms on their site.

## 2. Configure the repository (after approval)

SignPath gives you an organization ID and creates a project and a signing policy. In GitHub, go to
**Settings → Secrets and variables → Actions** and add:

| Kind | Name | Value |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | API token of the SignPath CI user |
| Variable | `SIGNPATH_ORGANIZATION_ID` | your organization ID |
| Variable | `SIGNPATH_PROJECT_SLUG` | e.g. `system-monitor-windows` |
| Variable | `SIGNPATH_POLICY_SLUG` | `release-signing` (or the name SignPath gives it) |

In the SignPath project, set the **artifact configuration** to sign both exes inside the uploaded zip:

```xml
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <zip-file>
    <pe-file path="SystemMonitor-portable.exe"><authenticode-sign/></pe-file>
    <directory path="SystemMonitor">
      <pe-file path="SystemMonitor.exe"><authenticode-sign/></pe-file>
    </directory>
  </zip-file>
</artifact-configuration>
```

Once the secret exists, the workflow signs automatically. Without it, it publishes unsigned files.

## 3. Release

1. Set the version in `sysmon/__init__.py` (e.g. `0.2.0`) and optionally write
   `docs/release-notes/v0.2.0.md`.
2. Commit, then push a matching tag:
   ```powershell
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. The workflow builds, tests, signs, and creates the GitHub Release with both downloads.
   Depending on the signing policy, SignPath may ask you to approve each request.

Python, Qt and PySide6 DLLs inside the build are already signed by their publishers. Only our
two exes need signing.
