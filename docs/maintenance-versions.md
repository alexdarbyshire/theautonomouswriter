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
  from [Hugo 0.148.2's release metadata](https://api.github.com/repos/gohugoio/hugo/releases/tags/v0.148.2),
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
| Node | Keep 24 for form tests, as required by repository guidance. It remains supported; [Node's release schedule](https://nodejs.org/en/about/previous-releases) now lists 26 as the latest LTS. Action runtimes are separate from this test runtime. |
| Hugo | Keep 0.148.2 across installation and both deployments. Latest stable is [0.170.1](https://github.com/gohugoio/hugo/releases/tag/v0.170.1), but [Azure issue 1720](https://github.com/Azure/static-web-apps/issues/1720) remains open. A local newer build does not establish Oryx compatibility. |
| PaperMod | Keep `10d3dcc0e05cee0aaca58a1305a9d824b2cf9a2a`. Current [master at 1181196](https://github.com/adityatelange/hugo-PaperMod/commit/118119693d8b5ac211b939775678310973bcb232) requires Hugo 0.158.0 and fails with 0.148.2 (`Language.Direction` unavailable). Latest tagged release v8.0 predates the existing pin. |
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
- 129 Python tests, Ruff lint/format checks and 10 Node 24 form tests pass.
- Replacement Hugo install step succeeds and verifies the fixed digest. The
  installed standard Hugo builds 79 pages with the retained PaperMod commit.
- All four workflow YAML files parse. Their roles, triggers, permissions,
  concurrency, writer state staging and feature flags are preserved.
- Separate Python 3.11 API environment: SDK function discovery, unauthenticated
  rejection, text validation, encrypted dispatch and rate limiting pass offline.
- Azure deployment, Oryx builds and hosted Functions startup were not run locally.
  Those remain deployment checks. No live writer or paid model calls were run.
