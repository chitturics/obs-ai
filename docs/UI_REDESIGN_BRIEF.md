# UI Redesign Brief — User Feedback

## Core Problems
1. Too much vertical scrolling — pages are too long
2. Panels don't collapse — everything is always expanded
3. Docs and Admin share sidebar incorrectly
4. Not enough detail per section — shallow information
5. No role-based content (viewer vs admin)
6. Upgrade page needs vulnerability details per version

## Design Principles (from user feedback)
- Every panel must be collapsible
- Max 2 pages of scroll — use tabs, accordions, modals
- Use full screen width (grid layouts, not just stacked cards)
- Context-aware sidebar (docs mode vs admin mode)
- Role-aware content (view vs edit based on role)
- Think from USER perspective — setup, test, validate flow

## Specific Fixes Needed

### Navigation
- Shared sidebar for docs + admin, but content changes based on context
- When viewing docs: sidebar shows doc sections
- When in admin: sidebar shows config sections
- Role check: VIEWER sees read-only, ADMIN sees edit controls

### Upgrade Readiness Page
- Collapsible version table (collapsed after selection)
- Timeline visual between current and target
- Per-version details: vulnerabilities, bugs fixed, breaking changes
- Why skip this version / why upgrade to this version
- Recommendation engine: "We recommend v10.2.4 because..."

### All Pages
- Every Card/section wrapped in `<details>` or collapsible component
- Default: most important sections open, rest collapsed
- Keyboard shortcut to expand/collapse all
- Breadcrumbs for deep navigation

### DocsPage
- Own layout (no admin sidebar)
- Table of contents on left
- Content on right
- Search within docs
- Accessible to ALL roles (no auth required for docs)
