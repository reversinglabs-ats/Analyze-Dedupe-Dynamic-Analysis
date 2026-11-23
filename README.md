# Analyze-Dedupe-Dynamic-Analysis

A small Python function (and command-line script) that submits a file to **ReversingLabs Spectra Analyze** for dynamic analysis **only if that file hasn't already been sent to the sandbox**. Drop it into any workflow or wrapper that uploads files to Spectra Analyze, so that a file submitted several times (by different users, retries, or re-runs of a pipeline) is sandboxed once instead of every time.

## Disclaimer of Warranty

This application is provided "as is" and "as available" without any warranties of any kind, either express or implied.

Reversing Labs make no representations or warranties of any kind, including but not limited to:

- The accuracy, completeness, or timeliness of the information submitted or received via this application;
- The functionality, availability, or performance of the application;
- The security, integrity, or confidentiality of submitted files or user data; or
- The fitness of this application for any particular purpose.

Use of this application is at your own risk. By using this application, you acknowledge that any data submitted to third-party services (e.g., ReversingLabs Spectra Analyze) may be subject to their own terms and conditions.

In no event shall the developer be liable for any direct, indirect, incidental, special, exemplary, or consequential damages arising out of or in any way connected with the use or misuse of this application.

## The problem

Many teams put their own submission portal or pipeline in front of Spectra Analyze, such as a software-onboarding or file-intake workflow, and request dynamic analysis on every upload. When the same file is submitted more than once, each upload can start another sandbox run. That wastes sandbox capacity and quota, and it produces duplicate results.

What Spectra Analyze does on its own (observed with ReversingLabs Cloud Sandbox):

| Situation | Behavior |
|---|---|
| The same file is uploaded again **while its sandbox run is still queued or running** | The upload is accepted (HTTP 201), but the duplicate run is dropped, with the warning `cloud_sandbox_already_running`. |
| The same file is uploaded again **after its sandbox run has finished** | **A new sandbox run starts.** There's no warning. |
| The same file is uploaded again **within a few seconds** of the first upload, before the appliance reports the sample | Any check made against the appliance in that window sees the file as new. |

This script covers the last two rows.

## When to use it

Use it when:

- Your workflow uploads files to Spectra Analyze **through the API**, requesting dynamic analysis, and
- the same file can come in more than once, and
- you want **one** sandbox result per unique file.

You may not need it when:

- **You only use CAPE or Joe Sandbox.** Spectra Analyze has a built-in setting for these: **Administration > Integrations & Connectors > Integrations > Submit only distinct files to CAPE / Joe Sandbox**. With it enabled, a file that has already been analyzed isn't sent to that sandbox again, whether it's re-submitted through the GUI or the API. The setting doesn't affect explicit reanalysis. See [Integrations](https://docs.reversinglabs.com/SpectraAnalyze/administration/integrations-connectors/integrations) and [Analysis services: submitting distinct files](https://docs.reversinglabs.com/SpectraAnalyze/analysis-services#submitting-distinct-files). The Integrations page lists the setting only for CAPE and Joe Sandbox. For ReversingLabs Cloud Sandbox and the other sandbox integrations, use this script.
- **You want a fresh run on purpose**, for example on a different OS platform or after a failed run. Call the [Reanalyze API](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation/reanalyze-api-v2) directly for those cases. Don't route them through `submit_once()`.

## How it works

For each file, `submit_once()`:

1. **Hashes the file locally** (SHA1). Nothing is sent yet.
2. **Checks its own in-flight set.** If this process already submitted the same SHA1, it skips the file without calling the API. This covers the few seconds after an upload before Spectra Analyze reports the sample.
3. **Asks Spectra Analyze whether the file exists:** `POST /api/samples/status/`. This returns `processed` (the sample is on the appliance) or `not_found`.
   See [Processing Status API](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation/processing#check-status-of-submitted-files).
4. **If the file exists, checks its sandbox status:** `POST /api/samples/v2/list/details/` with `fields=["rl_cloud_sandbox"]` and **`skip_reanalysis: "true"`**. Without `skip_reanalysis`, fetching a report reanalyzes the file, so the check itself would trigger the analysis you're trying to avoid.
   See [Full Report API](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation/full-report-api).
   If the sandbox section's `status` has **any value**, the file is skipped.
5. **Otherwise uploads it:** `POST /api/submit/file/` with an `analysis` object that requests dynamic analysis. It also adds the SHA1 to the in-flight set.
   See [Submissions API](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation/submissions).

```
file ──► SHA1 ──► in in-flight set? ──yes──► skip
                        │ no
                        ▼
          /api/samples/status/ ── not_found ──► upload with dynamic analysis
                        │ processed
                        ▼
          /api/samples/v2/list/details/ (skip_reanalysis=true)
                        │
          sandbox status set? ──yes──► skip
                        │ no (null)
                        ▼
                upload with dynamic analysis
```

### About the sandbox `status` field

The per-sandbox `status` field in the report **isn't described in the public API documentation.** These are the values seen in testing with ReversingLabs Cloud Sandbox:

| Value | Meaning |
|---|---|
| `null` | The file has never been sent to this sandbox. |
| `Queued` | The run is waiting to start. |
| `Processing` | The run is in progress. |
| `Reanalyzing` | A new run was started for a file that already had a report. |
| `Reported` | The sandbox report is available. |

Because it isn't documented, the script doesn't match on specific values. It treats any non-empty value as "already sandboxed". Before you rely on it, check it on your own appliance version (see [Verify on your appliance](#verify-on-your-appliance)). A failed run probably also leaves a non-empty status, so the script won't automatically retry a failed run. Use the Reanalyze API for that.

## Requirements

- Python 3.9 or later
- [`requests`](https://pypi.org/project/requests/)
- A Spectra Analyze API token for a user who can submit files and read reports. See [Spectra Analyze API documentation](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation).
- A sandbox integration configured on the appliance (ReversingLabs Cloud Sandbox by default).

```bash
pip install -r requirements.txt
```

## Configuration

Set the appliance URL and API token in the environment:

```bash
export ANALYZE_URL="https://analyze.example.com"
export ANALYZE_TOKEN="<your API token>"
```

Settings at the top of [`src/submit_once.py`](src/submit_once.py):

| Setting | Default | Purpose |
|---|---|---|
| `SANDBOX_FIELD` | `"rl_cloud_sandbox"` | The report field to check. Other sandbox integrations use `cape`, `joe`, `cuckoo`, `vmray_tcbase`, `fireeye` or `cisco_secure_malware_analytics`. |
| `ANALYSIS` | `{"rl_dynamic_analysis": {"platform": "windows10"}}` | The `analysis` object sent on upload. Change it to match `SANDBOX_FIELD` and the options you need (platform, other services). See the [Submissions API](https://docs.reversinglabs.com/SpectraAnalyze/api-documentation/submissions) for the full object. |
| `TIMEOUT` | `60` | Seconds per API call. |

**Change `SANDBOX_FIELD` and `ANALYSIS` together.** For example, for CAPE you'd check `"cape"` and send `{"cape": true}`.

If your appliance uses a certificate from an internal CA, set `REQUESTS_CA_BUNDLE=/path/to/ca.pem` instead of turning off certificate checking.

## Usage

### As a command-line script

```bash
python src/submit_once.py setup.exe installer.msi setup.exe
```

Each line is the path, the file's SHA1 (shortened here), and the result:

```
setup.exe d1150e... submitted
installer.msi 4a91c2... skipped: sandbox status is Reported
setup.exe d1150e... skipped: already submitted by this wrapper
```

### From your own wrapper

Replace your existing upload call with `submit_once()`:

```python
from submit_once import submit_once

sha1, result = submit_once("/uploads/setup.exe")

if result == "submitted":
    ...  # new analysis started; poll or wait for results as you do today
else:
    ...  # already sandboxed or in progress: fetch the existing report by sha1
```

`submit_once()` returns `(sha1, result)`, where `result` is one of:

- `"submitted"`: the file was uploaded with dynamic analysis.
- `"skipped: already submitted by this wrapper"`: this process uploaded the same file moments ago.
- `"skipped: sandbox status is <status>"`: Spectra Analyze already has a sandbox run (queued, in progress, or finished) for the file.

API errors (bad token, appliance unavailable, HTTP 4xx/5xx) raise `requests.HTTPError`.

### Running more than one copy of your wrapper

The in-flight set lives in memory in one Python process. If your wrapper runs as several workers, containers, or hosts, two of them can receive the same file at the same moment, and both can pass the appliance check before either upload shows up. To close that gap, replace `in_flight` with a shared store and **claim** the SHA1 atomically before checking. Examples:

- a database table with a **unique** SHA1 column (insert first; a duplicate-key error means another worker already has it)
- Redis `SET <sha1> 1 NX EX 600`

After the first few seconds the appliance check takes over, so the shared claim only has to last a short time.

## Verify on your appliance

Before you rely on the script, confirm the two lookups behave the same on your Spectra Analyze version. Use a file you've already submitted:

```bash
curl -X POST "$ANALYZE_URL/api/samples/status/" \
  -H "Authorization: Token $ANALYZE_TOKEN" -H "Content-Type: application/json" \
  -d '{"hash_values": ["<sha1>"]}'

curl -X POST "$ANALYZE_URL/api/samples/v2/list/details/" \
  -H "Authorization: Token $ANALYZE_TOKEN" -H "Content-Type: application/json" \
  -d '{"hash_values": ["<sha1>"], "fields": ["rl_cloud_sandbox"], "skip_reanalysis": "true"}'
```

The second response should contain `"rl_cloud_sandbox": {"results": [...], "status": "Reported", ...}`, or `"status": null` for a file that was never sandboxed.

## Limitations

- **Covers only API uploads that go through `submit_once()`.** Uploads made in the GUI, through other connectors, or through the reanalyze API bypass it.
- **Checks one sandbox.** Set `SANDBOX_FIELD` to the sandbox you use. If you send files to several sandboxes, check each one's field.
- **Relies on an undocumented field** (`status`). Re-check it after appliance upgrades.
- **Doesn't retry failed sandbox runs.** Use the Reanalyze API for those.
- **Tested** with ReversingLabs Cloud Sandbox. Other sandbox integrations expose a `status` field of the same shape in the report, but their behavior wasn't tested.

## Development

```bash
pip install -r requirements.txt ruff mypy pytest types-requests
ruff check .              # lint
ruff format --check .     # format check
mypy src tests            # type check
pytest                    # unit tests (Spectra Analyze API is mocked, no network needed)
```

## License

MIT. See [LICENSE](LICENSE).
