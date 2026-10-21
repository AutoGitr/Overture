# FastAPI 0.146.0 to 0.159.1 review

Reviewed against the [upstream release notes](https://fastapi.tiangolo.com/release-notes/)
on 2026-10-21. The dependency and lockfile now select 0.159.1.

## Release-by-release applicability

| Version | Upstream change | Overture decision |
| --- | --- | --- |
| 0.147.0 | Missing form booleans become false; upstream tests expanded. | No form endpoints. JSON boolean defaults remain intentional. |
| 0.148.0 | Omitted defaults, validation, factories and field-set tracking corrected. | SearchRequest defaults are valid; no request default depends on a validator. Retain defaults and test omitted query parameters. |
| 0.149.0 | Empty scalar form values are missing. | No form endpoints. |
| 0.150.0 | Unselected file inputs are missing. | No multipart uploads. |
| 0.151.0 | JSON null differs from omission. | Bulk stop explicitly accepts None; required request models reject null. Cover both over HTTP. |
| 0.152.0 | Header-model error locations corrected. | Headers use individual parameters, not models. |
| 0.153.0 | Form unions receive browser handling. | No form unions. |
| 0.154.0 | More Pydantic parameter validation options. | Existing Field constraints and shared Annotated parameter types already express the contracts. No additional coercion or validation policy needed. |
| 0.155.0 | Parameter extra keywords removed. | No unsupported parameter keywords found. |
| 0.156.0 | Field attributes preserved. | Keep declarative constraints; test SearchRequest boundaries and video-ID validation. |
| 0.156.1 | Metadata preserved without request options. | Existing annotations remain appropriate. |
| 0.156.2 | Metadata preserved for inferred parameters. | Required model bodies retain their schemas; regenerate contracts. |
| 0.156.3 | Query/header/cookie AliasChoices fixed. | No AliasChoices in API contracts. |
| 0.156.4 | Body/form AliasChoices fixed. | No AliasChoices in API contracts. |
| 0.156.5 | Path AliasChoices fixed. | Paths have one canonical name. |
| 0.156.6 | Parameter-model alias settings respected. | SearchRequest uses canonical names; no alias configuration to migrate. |
| 0.156.7 | Form/file alias error locations fixed. | No form/file endpoints. |
| 0.156.8 | File positions preserved during bytes conversion. | No file parameters. |
| 0.157.0 | Combined parameter models; boolean/nullability documentation; translation workflow cleanup. | No shared parameter bundles warrant splitting SearchRequest. Documentation and upstream automation require no application changes. |
| 0.158.0 | Combined form models. | No forms. |
| 0.158.1 | Form media types preserved. | No forms. |
| 0.158.2 | Optional form models. | No forms. |
| 0.159.0 | Optional query/header/cookie models. | SearchRequest always exists with meaningful defaults; making it optional would add a needless branch. |
| 0.159.1 | Optional form unions. | No forms. |

The baseline 0.146.0 root_path deprecation is already respected: Overture does
not pass root_path to FastAPI. No endpoint redesign is needed to receive the
applicable fixes. Retain native frontend serving, typed responses and Annotated
dependencies already used by the application.

## Verification

HTTP regression tests cover omitted query defaults, valid and invalid query
boundaries, video-ID validation, optional JSON bodies (absent, null and empty
object), and rejection of null for a required body. The normal repository gate
also checks every backend test, types, generated OpenAPI/client contracts and
dependency-provided skills.

## CI investigation

The latest 100 runs contain eight failed CI runs and three failed dependency
graph updates. Seven CI runs inherited a tool mismatch:
pyproject.toml required uv 0.13.4 while Dockerfile still selected 0.13.1.
Both the production image build and the existing tool-consistency test rejected
it. Remote main subsequently received the matching image pin and passed CI;
this checkout now includes that same pin. Older failed PR runs need a fresh
base/rebase, not changes to each unrelated dependency.

The earlier Actions-update failure had the inverse mismatch: setup-uv installed
0.13.4 while the project still required 0.13.1. Current workflows let setup-uv
read required-version from pyproject.toml, so that duplication is already gone.

The separate Dependabot Graph Update run failed because its installed Python
support ends at 3.14. Exact Python pinning does not resolve that limitation.
Keep Python 3.15 for the syntax this project uses; do not claim compatibility
with 3.14 to satisfy the graph updater. This hosted integration requires an
upstream runner update or a separately configured dependency submission path.

Evidence: [CI failure](https://github.com/AutoGitr/Overture/actions/runs/39680238840),
[dependency graph failure](https://github.com/AutoGitr/Overture/actions/runs/39680246125),
[subsequent passing main CI](https://github.com/AutoGitr/Overture/actions/runs/39681863882).
