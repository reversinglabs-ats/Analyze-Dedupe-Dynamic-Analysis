"""Submit a file to Spectra Analyze for dynamic analysis only if it hasn't been sandboxed yet.

Usage as a script:
    export ANALYZE_URL=https://analyze.example.com
    export ANALYZE_TOKEN=<api token>
    python src/submit_once.py setup.exe other.msi

Usage from a wrapper:
    from submit_once import submit_once
    sha1, result = submit_once("setup.exe")
"""

import hashlib
import json
import os
import sys

import requests

# Spectra Analyze report field for the sandbox to check, and the matching
# `analysis` object sent on upload. Change both to use a different sandbox.
SANDBOX_FIELD = "rl_cloud_sandbox"
ANALYSIS = {"rl_dynamic_analysis": {"platform": "windows10"}}

TIMEOUT = 60  # seconds per API call

# SHA1s this wrapper has submitted. Covers the short window after an upload
# before Spectra Analyze reports the sample. If the wrapper runs as several
# processes or hosts, keep this in a shared store (a database table with a
# unique SHA1 column, Redis SETNX, ...) instead of a Python set.
in_flight: set[str] = set()


def submit_once(path: str) -> tuple[str, str]:
    url = os.environ["ANALYZE_URL"].rstrip("/")
    headers = {"Authorization": "Token " + os.environ["ANALYZE_TOKEN"]}

    with open(path, "rb") as f:
        sha1 = hashlib.sha1(f.read(), usedforsecurity=False).hexdigest()

    if sha1 in in_flight:
        return sha1, "skipped: already submitted by this wrapper"

    # 1. Is the file already on the appliance?
    r = requests.post(
        url + "/api/samples/status/",
        headers=headers,
        json={"hash_values": [sha1]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    if r.json()["results"][0]["status"] == "processed":
        # 2. Has the sandbox already been queued, run, or reported for it?
        #    skip_reanalysis stops this lookup from triggering a reanalysis.
        r = requests.post(
            url + "/api/samples/v2/list/details/",
            headers=headers,
            json={"hash_values": [sha1], "fields": [SANDBOX_FIELD], "skip_reanalysis": "true"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        sandbox_status = r.json()["results"][0][SANDBOX_FIELD]["status"]
        if sandbox_status:
            return sha1, "skipped: sandbox status is " + sandbox_status

    # 3. Not seen before, or never sandboxed: submit it with dynamic analysis.
    in_flight.add(sha1)
    with open(path, "rb") as f:
        r = requests.post(
            url + "/api/submit/file/",
            headers=headers,
            files={"file": f},
            data={"analysis": json.dumps(ANALYSIS)},
            timeout=TIMEOUT,
        )
    r.raise_for_status()
    return sha1, "submitted"


if __name__ == "__main__":
    for file_path in sys.argv[1:]:
        print(file_path, *submit_once(file_path))
