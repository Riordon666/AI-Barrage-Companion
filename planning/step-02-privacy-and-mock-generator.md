# Step 02: Privacy Guard and Mock Barrage Generator

## 1. Goal

This step adds the first runnable generation path after the scaffold:

- Filter scene context through a privacy boundary before generation.
- Generate local mock barrage items without API keys or network access.
- Add tests that lock the expected behavior.

This step still does not implement screen capture, frame analysis, AI API calls, barrage scheduling, or PySide6 rendering.

## 2. Files Added or Updated

Added:

```text
app/core/privacy_guard.py
app/core/mock_barrage_service.py
tests/test_privacy_guard.py
tests/test_mock_barrage_service.py
planning/step-02-privacy-and-mock-generator.md
```

Updated:

```text
main.py
planning/project-plan.md
planning/implementation-roadmap.md
planning/step-01-scaffold-and-interfaces.md
```

## 3. PrivacyGuard Implementation

`BasicPrivacyGuard` was added in:

```text
app/core/privacy_guard.py
```

It accepts a `SceneSummary` and `AppSettings`, then returns a `PrivacyDecision`.

Default strict mode blocks these sensitive context fields:

```text
screenshot
ocr_text
window_title
file_name
url
chat_text
```

The current `SceneSummary` only contains coarse fields:

- activity
- pace
- event
- confidence

So the guard allows the sanitized scene through while explicitly documenting which richer context fields must not reach AI generation in MVP.

Reason:

The project promise is not just “do not upload screenshots.” Even OCR text, window titles, file names, URLs, and chat text can leak private information. The guard creates one mandatory boundary for future AI calls.

## 4. MockBarrageService Implementation

`MockBarrageService` was added in:

```text
app/core/mock_barrage_service.py
```

It implements local barrage generation based on:

- `SceneSummary.event`
- requested personas
- requested count

Supported scene events:

- `normal`
- `highlight`
- `stuck`
- `idle`

Supported personas:

- `troll`
- `support`
- `sarcastic`
- `follower`
- `fun`

Behavior:

- Returns `GenerationResult(source="mock")`.
- Clamps request count to at most 5 items.
- Generates short text suitable for barrage display.
- Assigns priority `10` for `highlight`, `5` for `stuck`, and `0` for normal or idle scenes.
- Generates unique item IDs.

Reason:

Mock generation lets the project validate the generation pipeline before API keys, network requests, prompt design, or model response parsing exist.

## 5. Entry Point Update

The root `main.py` now runs a tiny integration path:

```text
SceneSummary
-> BasicPrivacyGuard
-> MockBarrageService
-> console output
```

Run:

```powershell
python main.py
```

Expected shape:

```text
AI Barrage Companion scaffold ready
density=medium, cost_mode=balanced
privacy_allowed=True
mock_barrages=...
```

The exact mock barrage texts can vary because the service randomly chooses from local templates.

## 6. Tests Added

Added privacy tests:

- Strict mode blocks screenshot, OCR text, window title, file name, URL, and chat text.
- Scene confidence is clamped into `0.0` to `1.0`.
- Balanced mode respects optional OCR and window title flags.

Added mock generator tests:

- Generates the requested count.
- Returns `source="mock"`.
- Assigns expected persona values.
- Assigns highlight priority.
- Clamps count to 5.
- Uses stuck priority.

## 7. Current Status

Completed:

- Basic privacy filtering
- Local mock barrage generation
- Minimal integration in `main.py`
- Unit tests for privacy and mock generation

Still not completed:

- Real screen capture
- Frame difference analysis
- AIService
- BarrageCache
- BarrageManager
- PySide6 overlay window
- Control panel

## 8. Next Step

Next recommended step: implement `BarrageManager`. This has been completed in step 03. See `step-03-barrage-manager.md`.

Reason:

The project can now generate barrage items, but it cannot queue, deduplicate, limit density, assign tracks, pause, or resume them. `BarrageManager` is the next needed layer before building the PySide6 overlay.
