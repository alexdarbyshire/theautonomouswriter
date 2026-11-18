# Version audit: 2026-11-18

Question: which current stable updates fit the existing writer and Azure
deployment contracts? Release and package metadata were checked on 2026-11-18.

## Actions and installation

- GitHub-maintained actions: [checkout 7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1),
  [setup-python 7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0)
  and [setup-node 7.1.0](https://github.com/actions/setup-node/releases/tag/v7.1.0).
  Their migration notes preserve our inputs on GitHub-hosted runners. Checkout's
  new restriction concerns privileged fork triggers, which these workflows do
  not use; setup-node's token change concerns registry configuration we do not use.
- Retain publisher-maintained [setup-uv 10.3.3](https://github.com/astral-sh/setup-uv/releases/tag/v10.3.3)
  at commit `68559e99cc807c1eb7e9238fd43a15bba460eec2`. Reviewed its action
  definition, setup, download and checksum paths: Node 24; archive verification
  precedes extraction; a supplied checksum takes priority. Pin
  [uv 0.13.9](https://github.com/astral-sh/uv/releases/tag/0.13.9) and its upstream
  Linux x86-64 archive digest. This is a bounded source review, not a complete
  audit of its bundled JavaScript or dependencies.
- Remove `peaceiris/actions-hugo`. Reviewing [3.3.0's installer](https://github.com/peaceiris/actions-hugo/blob/d1c81a15d4e6dca7086a17b9c2565cb70fd576bf/src/installer.ts)
  found no Hugo archive verification. Use a shell download with a fixed digest
  from [Hugo 0.170.1's release metadata](https://api.github.com/repos/gohugoio/hugo/releases/tags/v0.170.1),
  checked before extraction. It installs the same standard Linux amd64 edition.
- Retain Microsoft's [Azure deployment action](https://github.com/Azure/static-web-apps-deploy/tree/1a947af9992250f3bc2e68ad0754c0b0c11566c9)
  at the current `v1` commit, `1a947af9992250f3bc2e68ad0754c0b0c11566c9`.
  Reviewed its action definition, Dockerfile and entrypoint. The wrapper invokes
  Microsoft's deployment client. Its Dockerfile still pulls
  `mcr.microsoft.com/appsvc/staticappsclient:stable`; the SHA pins the wrapper,
  not that image or Oryx. No GitHub-maintained equivalent supplies this deployment.

## Runtime and site pins

| Surface | Decision and evidence |
| --- | --- |
| Python | Keep 3.11 for the writer and CI, testing the declared minimum. [Python's lifecycle](https://devguide.python.org/versions/) supports it through October 2027; current stable is 3.15. |
| Node | Use 26 for form tests, matching the latest LTS in [Node's release schedule](https://nodejs.org/en/about/previous-releases). Tested locally with 26.13.1. Action runtimes are separate from this test runtime. |
| Hugo | Use current stable [0.170.1](https://github.com/gohugoio/hugo/releases/tag/v0.170.1) across installation and both deployments. Although [Azure issue 1720](https://github.com/Azure/static-web-apps/issues/1720) remains open, today's Azure image successfully downloads and builds this version through Oryx; see validation below. |
| PaperMod | Keep `10d3dcc0e05cee0aaca58a1305a9d824b2cf9a2a`. The existing theme builds with Hugo 0.170.1, with deprecation warnings. Latest tagged release v8.0 predates this pin. Updating to current master would also introduce template and visual changes; retain the working theme for this maintenance PR. |
| Azure Functions | Explicitly select `python:3.11` and pin SDK 1.26.0 and cryptography 50.0.2. [SWA configuration documentation](https://learn.microsoft.com/en-us/azure/static-web-apps/configuration#platform) lists 3.11. Its [API overview](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-functions) still stops at 3.10; use the configuration reference for the supported setting. [SDK 2.4.0](https://pypi.org/pypi/azure-functions/2.4.0/json) requires Python 3.13, beyond the documented managed runtime. Keep the Functions 4.x extension bundle. |

## Python packages

Refresh `uv.lock` to compatible stable releases from PyPI. Direct resolutions:
Pydantic 2.14.3, OpenAI 3.54.0, Tavily 0.8.5, atproto 0.0.75,
cryptography 50.0.2, pytest 9.2.0 and Ruff 0.17.5. The lockfile retains
the resolved transitive packages and artifact hashes.

- [atproto's changelog](https://github.com/MarshalX/atproto/blob/main/CHANGES.md)
  covers 0.0.66 through 0.0.75: SDK/lexicon updates and additive OAuth support.
  Retain app-password login. Raising the explicit pin also permits current
  cryptography. Actual client namespaces, link facets and reply models were
  checked offline in addition to the existing mocked behavior tests.
- [OpenAI's 3.0 migration](https://github.com/openai/openai-python/blob/main/CHANGELOG.md)
  changes the default transport to HTTPX2. The writer uses the default client,
  without a custom HTTPX transport. New offline tests exercise real SDK request
  serialization, response parsing and exhausted 429 retries.
- Package metadata: [Pydantic](https://pypi.org/pypi/pydantic/json),
  [OpenAI](https://pypi.org/pypi/openai/json), [Tavily](https://pypi.org/pypi/tavily-python/json),
  [atproto](https://pypi.org/pypi/atproto/json), [cryptography](https://pypi.org/pypi/cryptography/json),
  [pytest](https://pypi.org/pypi/pytest/json), [Ruff](https://pypi.org/pypi/ruff/json)
  and [Azure Functions](https://pypi.org/pypi/azure-functions/json).

## Validation and limits

- `uv sync --locked` succeeds with CI's uv 0.13.9 on Python 3.11.15.
- 129 Python tests, Ruff lint/format checks and 10 Node 26.13.1 form tests pass.
- Replacement Hugo install step succeeds and verifies the fixed digest. The
  installed Hugo 0.170.1 builds 79 pages with the retained PaperMod commit.
- All four workflow YAML files parse. Their roles, triggers, permissions,
  concurrency, writer state staging and feature flags are preserved.
- Separate Python 3.11 API environment: SDK function discovery, unauthenticated
  rejection, text validation, encrypted dispatch and rate limiting pass offline.
- Azure image `mcr.microsoft.com/appsvc/staticappsclient:stable` resolved to digest
  `sha256:026b202feacf67ec0acd4846a1d17953f6c3c8ff912a1c0ec29aa6000a495f12`.
  In that image, Oryx `0.2.20260728.2` downloaded Hugo 0.170.1 and built the
  existing site successfully (79 pages). Reproduction: mount `site/` read-only,
  copy it to `/tmp/site`, and run `ENABLE_DYNAMIC_INSTALL=true oryx build
  /tmp/site -o /tmp/site-output --platform hugo --platform-version 0.170.1`.
- This image digest records test evidence; workflows continue using Microsoft's
  normal image channel. No deployment, hosted Functions startup, live writer or
  paid model calls were run.
