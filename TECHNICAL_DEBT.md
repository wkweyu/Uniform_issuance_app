# Technical Debt

## TD-001

Description: Configure and document an approved production deployment target for the existing published container image, including target-specific secret management and a post-deployment verification record.

Priority: High

Impact: The repository can publish a container image, but cannot execute a production deployment rehearsal from source control alone.

Target Version: v2 / Operations release enablement

## TD-002

Description: Establish a reproducible production-like backup, restore, and migration-rehearsal fixture with sanitized data and retained evidence.

Priority: High

Impact: Automated migration preflight is available, but final backup/restore and rollback certification requires an approved database copy.

Target Version: v2 / Operations release enablement

## TD-003

Description: Maintain a supported-browser, tablet, printer, and accessibility UAT test record for the Finance workspace and print outputs.

Priority: Medium

Impact: Unit and integration coverage does not substitute for interactive device and physical-print validation.

Target Version: v2 / Quality operations

## TD-004

Description: Define production data-volume response-time thresholds for student search, receipt posting, statement retrieval, and report exports.

Priority: Medium

Impact: The release suite validates correctness but does not establish production-size performance acceptance criteria.

Target Version: v2 / Quality operations

## TD-005

Description: Repair non-Finance root-suite isolation: attendance and tenancy route tests must provide a MySQL-backed or fully mocked entitlement fixture, and platform-route assertions must be synchronized with the current rendered UI.

Priority: Medium

Impact: The root suite, executed with the duplicate local workspace excluded, produced `507 passed, 18 failed`. The failures do not exercise Finance RC1, whose dedicated regression suite passes, but they prevent a clean all-domain local regression run.

Target Version: v2 / Platform and attendance quality