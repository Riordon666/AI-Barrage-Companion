# Step 03: Barrage Manager

## 1. Goal

This step adds the scheduling layer between barrage generation and future UI rendering.

Before this step, the project could generate `BarrageItem` objects, but it could not decide:

- which items should be displayed first
- how many items can be displayed at once
- which track each item should use
- whether duplicate text should be suppressed
- what happens during pause and resume

## 2. Files Added or Updated

Added:

```text
app/core/barrage_manager.py
tests/test_barrage_manager.py
planning/step-03-barrage-manager.md
```

Updated:

```text
app/constants.py
main.py
planning/project-plan.md
planning/implementation-roadmap.md
planning/step-02-privacy-and-mock-generator.md
```

## 3. Implementation

`BasicBarrageManager` was added in:

```text
app/core/barrage_manager.py
```

It implements the existing `BarrageManager` protocol shape:

- `enqueue(items)`
- `tick(now, viewport_width, viewport_height)`
- `set_density(density)`
- `pause()`
- `resume()`

`tick()` returns newly scheduled `TrackAssignment` objects. The future PySide6 overlay can use these assignments to render and animate barrage items.

## 4. Scheduling Rules

Implemented density limits:

```text
low    -> 3 visible items
medium -> 6 visible items
high   -> 10 visible items
```

Implemented track behavior:

- Track count is also limited by viewport height.
- New items use the lowest available track index.
- Active tracks are released after `item.duration_seconds`.
- Each assignment includes `track_index`, `start_x`, `y`, and `speed_px_per_second`.

Implemented de-duplication:

- Empty text is ignored.
- Duplicate pending text is ignored.
- Duplicate active text is ignored.
- Recently displayed text is blocked for `DEFAULT_DUPLICATE_WINDOW_SECONDS`.

Implemented priority:

- Pending items are sorted by priority descending.
- When priorities match, older `created_at` values are scheduled first.

Implemented pause and resume:

- `pause()` prevents new assignments.
- `resume()` allows pending items to be scheduled again.

## 5. Entry Point Update

Root `main.py` now demonstrates this minimal chain:

```text
SceneSummary
-> BasicPrivacyGuard
-> MockBarrageService
-> BasicBarrageManager
-> TrackAssignment output
```

Run:

```powershell
python -B main.py
```

Expected shape:

```text
AI Barrage Companion scaffold ready
density=medium, cost_mode=balanced
privacy_allowed=True
mock_barrages=...
scheduled_tracks=0, 1, 2
```

The exact barrage text can vary because mock generation chooses from local templates.

## 6. Tests Added

`tests/test_barrage_manager.py` covers:

- low density schedules at most 3 items
- active tracks release after duration
- pending items continue after track release
- duplicate text is suppressed
- duplicate text can return after the duplicate window expires
- pause blocks new assignments
- resume schedules pending items
- higher priority items are scheduled first
- viewport height limits track capacity
- invalid density raises `ValueError`

## 7. Current Status

Completed:

- Queueing
- De-duplication
- Density limiting
- Track assignment
- Pause and resume
- Priority ordering
- Unit tests for scheduling behavior

Still not completed:

- Real screen capture
- Frame difference analysis
- AIService
- BarrageCache
- PySide6 overlay window
- Control panel

## 8. Important Note

This step intentionally does not implement visual movement. `BasicBarrageManager` only decides what should be rendered and where it starts. The next UI layer is responsible for drawing and animating those assignments.

Reason:

Keeping scheduling separate from PySide6 prevents UI code, AI generation, and queue logic from becoming tightly coupled.

## 9. Next Step

Next recommended step: implement a minimal PySide6 overlay renderer.

Reason:

The project can now generate and schedule barrage items, but the user still cannot see them on screen. A minimal transparent overlay will validate the core product experience before adding screen capture or real AI.
