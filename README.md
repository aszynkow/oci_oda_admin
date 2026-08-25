# OCI ODA Admin

`oda` is a local Python CLI for building, validating, publishing, running, and observing Oracle Digital Assistant (ODA) skills and digital assistants.

It uses the OCI Python SDK for supported lifecycle operations and signed ODA REST calls for Insights exports and other REST-only features.

## Start here

From this repository, install the CLI once:

```bash
python3 scripts/setup_cli.py
```

Open a new terminal, then confirm it is available:

```bash
oda --help
oda validate
```

The short command is `oda`. `oda-admin` is an equivalent alias.

### Command reference

Run `oda --help` at any time for the live command list. The main commands are:

| Group | Commands |
|---|---|
| Develop locally | `validate`, `render`, `local-run`, `test`, `serve-local-html` |
| Build and publish | `export-skill`, `download-bundle`, `repair-bundle`, `upload-bundle`, `import-skill`, `repair-assistant-bundle`, `import-assistant`, `train-publish` |
| Discover and operate | `discover`, `discover-sdk`, `instances`, `bots`, `skills`, `channels`, `channel-details`, `route-web-channel`, `start-channel` |
| Observe and export | `export-logs`, `export-insights` |
| Advanced API access | `deploy`, `rest`, `create-skill` |

Most cloud-changing commands need `--apply`. Commands without `--apply` either
run locally, read configuration, or show a dry-run plan.

![Example output from `oda --help`](docs/images/oda-help.png)

Before running the real local Web widget, create the local-only credentials
file from the safe template and replace the placeholder with the Oracle Web
channel secret:

```bash
cp configs/local-web.credentials.example.json configs/local-web.credentials.json
```

`configs/local-web.credentials.json` is ignored by Git. Do not commit or share
the channel secret.

## The normal workflow

```mermaid
flowchart LR
  A[Edit YAML source] --> B[Validate and test locally]
  B --> C[Repair or import ODA bundle]
  C --> D[Train and publish]
  D --> E[Route Web channel]
  E --> F[Run real local Web widget]
  F --> G[Export Insights to Object Storage]
  G --> H[Use CSV files in Oracle Analytics Cloud]
```

## Project files

| File | Purpose |
|---|---|
| `configs/oci-admin.yaml` | Main source of truth: instance, skill, assistant, channel, bundles, and Insights destination. |
| `configs/local-web.credentials.example.json` | Safe template for local Web credentials. |
| `configs/local-web.credentials.json` | Local Web channel secret. Git ignored; never commit it. |
| `scripts/setup_cli.py` | Python installer for `oda` and `oda-admin`. |
| `exports/` | Downloaded bundles and Insights files. Git ignored. |
| `logs/` | Local test and command artifacts. Git ignored. |

Use profile `apacanzset03` for OCI commands in this environment:

```bash
oda discover-sdk --profile apacanzset03
```

## 1. Develop and test locally

Edit [`configs/oci-admin.yaml`](configs/oci-admin.yaml), then validate and run the complete local test suite:

```bash
oda validate
oda render
oda local-run "What can you do?"
oda test
```

`local-run` is an offline intent-and-response check. `test` checks every configured utterance and verifies that each Visual Flow has a response state. It does not call OCI or make a compute change.

## 2. Repair and publish a Visual Flow bundle

ODA Visual Flow state updates are safely handled as an export, local repair, and import workflow.

```bash
# Export the current skill to the configured existing Object Storage bucket.
oda export-skill --object-name oda-admin/bundles/oci-admin-v1.3.zip --apply \
  --profile apacanzset03

# Download and repair the exported bundle locally.
oda download-bundle --object-name oda-admin/bundles/oci-admin-v1.3.zip \
  --output exports/oci-admin-v1.3.zip --profile apacanzset03
oda repair-bundle --source exports/oci-admin-v1.3.zip \
  --output exports/oci-admin-v1.4-repaired.zip --skill-version 1.4

# Upload and import the repaired skill as a new draft version.
oda upload-bundle --bundle exports/oci-admin-v1.4-repaired.zip \
  --object-name oda-admin/bundles/oci-admin-v1.4-repaired.zip --profile apacanzset03
oda import-skill --object-name oda-admin/bundles/oci-admin-v1.4-repaired.zip \
  --apply --profile apacanzset03
```

Create the matching assistant bundle so it embeds the repaired skill version:

```bash
oda export-assistant --object-name oda-admin/bundles/test-v1.3.zip --apply \
  --profile apacanzset03
oda download-bundle --object-name oda-admin/bundles/test-v1.3.zip \
  --output exports/test-v1.3.zip --profile apacanzset03
oda repair-assistant-bundle --source exports/test-v1.3.zip \
  --repaired-skill exports/oci-admin-v1.4-repaired.zip \
  --output exports/test-v1.4-repaired.zip --assistant-version 1.4 --skill-version 1.4
oda upload-bundle --bundle exports/test-v1.4-repaired.zip \
  --object-name oda-admin/bundles/test-v1.4-repaired.zip --profile apacanzset03
oda import-assistant --object-name oda-admin/bundles/test-v1.4-repaired.zip \
  --apply --profile apacanzset03
```

After import, discover the new draft skill and assistant IDs and update the `resources` section in YAML before publishing:

```bash
oda discover-sdk --profile apacanzset03
oda train-publish --apply --profile apacanzset03
```

`train-publish` refuses to publish if a configured flow has no response state.

## 3. Route the live Web channel

Inspect the channel before changing it:

```bash
oda channel-details a5c83739-7a61-4d99-bb3b-295ce0630cc8 \
  --oda-instance-id <oda-instance-ocid> --profile apacanzset03
```

Preview a route change by omitting `--apply`. Add `--apply` only when the assistant version is published and ready for live traffic:

```bash
oda route-web-channel <channel-id> <published-assistant-id> \
  --oda-instance-id <oda-instance-ocid> --profile apacanzset03 --apply
```

## 4. Run the real Oracle Web widget locally

The local page uses Oracle's Web SDK and the authenticated `demotest` channel. It shows Oracle's real lower-right chat launcher; it is not a simulated chat page.

Ensure `configs/local-web.credentials.json` exists first, using the template in
the setup section above.

```bash
oda serve-local-html --port 8080 \
  --assistant-id 28C7ACB1-76B8-4EC6-8286-AF195BB2531B
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/). Stop the local server with `Ctrl+C`.

The channel secret stays on the local Python server. It creates short-lived JWTs for the browser and never sends the secret to the page.

## 5. Export ODA Insights for Oracle Analytics Cloud

`export-insights` creates an ODA Insights export job, waits for it, downloads the raw ZIP, extracts each CSV, writes a manifest, and uploads to an **existing** bucket. It never creates, deletes, or changes a bucket.

Start with the dry run:

```bash
oda export-insights --begin 2026-08-24 --end 2026-08-24
```

Then run the export. `--bucket` is optional when `insights.object_storage.bucket` is set in YAML.

```bash
oda export-insights --begin 2026-08-24 --end 2026-08-24 \
  --bucket oda --profile apacanzset03 --apply
```

The output is preserved without merging incompatible schemas:

```text
insights/
├── archive/2026/08/oda-insights-2026-08-24.zip
└── analytics/
    ├── conversations/2026/08/conversations-2026-08-24.csv
    ├── intents/2026/08/intents-2026-08-24.csv
    └── manifests/2026/08/oda-insights-2026-08-24.json
```

Each source CSV becomes a separate Object Storage object. Create separate OAC tables from those files, then join them in an OAC dataset when their keys and schemas warrant it. The manifest records each file's source, size, checksum, and Object Storage path.

ODA Insights export needs IAM permission to use the ODA instance resource and Object Storage permission to put objects in the selected existing bucket.

## 6. Archive local CLI artifacts

For local tests, plans, and command logs (not ODA service-side Insights), use:

```bash
oda export-logs
oda export-logs --upload --namespace sdncspltazsk --bucket oda \
  --profile apacanzset03
```

## Python fallback

If `oda` is unavailable in a shell, run the same CLI through Python from the repository root:

```bash
.venv/bin/python -m oci_oda_admin.cli validate
.venv/bin/python -m oci_oda_admin.cli test
.venv/bin/python -m oci_oda_admin.cli export-insights \
  --begin 2026-08-24 --end 2026-08-24 --profile apacanzset03 --apply
```

## Safety model

- Commands that change cloud state require `--apply`.
- `export-insights` only writes objects into an existing bucket.
- The local Web secret is ignored by Git and stays server-side.
- The current intent flows return safe messages. Connecting intents to real OCI Compute, Monitoring, Cost, Support, and Alarm actions is a separate build step and should include compartment scoping and confirmation for mutations.

## Quality checks

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## References

- [OCI Python SDK ODA API](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/oda.html)
- [Oracle Web SDK](https://docs.oracle.com/en/cloud/paas/digital-assistant/sdk-js/)
- [ODA Insights Export API](https://docs.oracle.com/en/cloud/paas/digital-assistant/rest-api-oci/api-insights-export.html)
- [Oracle Analytics Cloud: OCI Object Storage datasets](https://docs.oracle.com/en/cloud/paas/analytics-cloud/acubi/create-dataset-from-oci-object-storage.html)
