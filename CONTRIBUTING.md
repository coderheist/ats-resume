# Contributing

Thanks for working on this project. This document covers the workflow and the
standards a change is expected to meet.

- [Getting set up](#getting-set-up)
- [Workflow](#workflow)
- [Commit messages](#commit-messages)
- [Pull requests](#pull-requests)
- [Code standards](#code-standards)
- [Testing requirements](#testing-requirements)
- [Documentation requirements](#documentation-requirements)
- [Reporting bugs](#reporting-bugs)

---

## Getting set up

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for full setup. The short version:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd frontend-react && npm install && cd ..

venv/Scripts/python -m pytest        # Windows
python -m pytest                     # macOS/Linux
```

Use the virtualenv's interpreter. A system Python with a different `starlette`
version produces spurious payment-test failures.

---

## Workflow

1. **Open an issue first** for anything beyond a small fix, so the approach can
   be agreed before you spend time on it.
2. **Branch from `main`**:
   ```bash
   git checkout -b fix/parse-provider-crash
   ```
   Prefixes: `feat/`, `fix/`, `docs/`, `test/`, `refactor/`, `chore/`.
3. **Write a failing test first** for a bug fix. It should fail before your
   change and pass after.
4. **Keep the change focused.** Unrelated refactors belong in their own PR.
5. **Run both suites** before pushing.
6. **Update documentation** in the same PR as the change.

---

## Commit messages

Conventional Commits:

```
<type>(<scope>): <subject>

<body — why, not what>
```

Types: `feat` · `fix` · `docs` · `test` · `refactor` · `perf` · `chore`

```
fix(resume): return the provider that actually answered

The route computed provider_used from the requested tier, which is None
on the default no-tier path even when the confidence gate escalated and
an LLM answered. That produced an AttributeError and a 500 on the main
upload path whenever an API key was configured.

ParsedResumeResult now carries the resolved provider, so the route
reports what actually ran instead of re-deriving it from the request.
```

Explain the reasoning. The diff already shows what changed.

---

## Pull requests

Include:

- **What changed and why.** Link the issue.
- **How it was verified.** Commands run, results. Say plainly if something could
  not be verified — an untested claim is worse than an acknowledged gap.
- **Documentation updates**, if any behavior changed.

Checklist:

- [ ] Both test suites pass (excluding the six known environment-dependent
      failures — see [DEVELOPMENT.md](docs/DEVELOPMENT.md#currently-failing-tests))
- [ ] New logic has tests
- [ ] Public API changes are reflected in [docs/API.md](docs/API.md)
- [ ] New environment variables are in `.env.example` **and**
      [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- [ ] No secrets, keys, or `.env` files committed
- [ ] No model identifier introduced outside `app/core/llm/router.py`

---

## Code standards

### Python

```python
from __future__ import annotations   # first line of every module
```

- Modern type hints: `str | None`, not `Optional[str]`.
- Dataclasses for domain results; Pydantic only at the API boundary.
- Routes stay thin — validate, delegate, shape the response. Logic lives in
  `app/core/`.
- `app/core/` must not import FastAPI. Raise domain exceptions and let the route
  layer translate them into status codes.
- Never write a model identifier outside `router.py`.

### Docstrings explain reasoning

This codebase's docstrings are unusually substantial by design. They record why a
decision was made, what was rejected, and what the code does **not** handle.
Match that standard:

```python
def compute_confidence(resume: JsonResume, raw_text: str) -> float:
    """
    Five auditable signals, each worth a fixed share -- not a black box,
    and deliberately not ML-based: a gate that decides whether an LLM
    call is warranted must not itself cost an LLM call.

    The threshold is conservative on purpose. A wrong parse shown to a
    user is worse than one extra LLM call, so this errs toward escalating
    when genuinely uncertain.
    """
```

State limitations directly. A resume tool that overstates its own accuracy
undermines its own purpose, and the same applies to its documentation.

### JavaScript / React

- Function components with hooks.
- Data fetching in feature hooks, not components.
- Plain CSS with custom properties from `styles/tokens.css`.
- All API calls through `lib/api.js`, which attaches the auth token
  automatically.
- Accessibility is not optional: real `<button>` elements, `label`/`htmlFor`
  pairs, meaningful `aria` only where semantics do not already carry it.

### Dependencies

The standing preference is to own what is simple enough to own. The rate limiter
is about forty lines rather than `slowapi`; the embedding fallback was fixed
rather than replaced with a library. Add a dependency when it does something
genuinely hard, and justify it in the PR.

---

## Testing requirements

| Change | Required tests |
| --- | --- |
| Bug fix | A regression test that fails before the fix |
| New scoring logic | Unit tests including boundary values |
| New endpoint | `TestClient` tests for success and every documented error |
| New component | Testing Library tests for render and interaction |
| Refactor | Existing tests must pass unchanged |

**Do not write tests that depend on ambient environment variables.** Six tests
currently fail on any machine with real Firebase credentials configured, because
they assert an unconfigured code path and read the developer's actual
environment to get there. Stub the configuration check instead —
`monkeypatch.delenv` on the backend, mocking `isFirebaseConfigured` on the
frontend.

---

## Documentation requirements

Update documentation in the same PR as the change.

| Change | Update |
| --- | --- |
| New or changed endpoint | [docs/API.md](docs/API.md) |
| New environment variable | `.env.example` **and** [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| New scoring dimension or weight | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/API.md](docs/API.md) |
| New setup step | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Production-affecting change | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| A known issue fixed | Remove it from every "Known issues" list |

Example payloads in `docs/API.md` are captured from a running instance, not
written by hand. If you change a response shape, capture the new one rather than
editing the JSON by eye.

---

## Reporting bugs

Include:

- What you expected and what happened
- Minimal reproduction steps
- The relevant environment: Python version, interpreter used, which optional
  integrations are configured
- Full traceback or console output

Configuration state matters more than usual here, because many behaviors change
based on which integrations are present. "Parsing returns 500" and "parsing
returns 500 with an LLM key configured and no tier passed" are very different
reports — the second one identifies the bug.

### Security issues

Do not open a public issue for a security vulnerability. Report it privately to
the maintainers.
