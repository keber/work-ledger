# Open questions

## To verify

- **Session titles and sidebar groups**: resolved for titles: transcripts carry `custom-title`, `agent-name` and `ai-title` records (verified 2026-11-04). Still open for sidebar groups. Custom titles are also local (`<transcript-id>/custom-title.json`, 36 found). Auto-generated titles, sidebar groups and the app-id ↔ CLI-id mapping live in the desktop app's state. The scanner CLI cannot call the app's session tools. Candidates: read the app's local data, or have the pane (or a Claude session) export them to a file.
- **Codex JSONL format**: confirm fields for cwd, branch, and tool calls with file paths.
- **Engram access from the CLI**: read its store directly or through its CLI.

## To decide

- Implementation language and runtime for the scanner CLI.
- Ledger schema (`ledger.json`, `overrides.json`).
- Contents and layout of the pane.
- Cadence and channel of the 15-day reminder and the weekly curation day.
- Destination for approved communication pieces (wiki or folder) and the sanitization rules.
- Prioritization: what signal the tool uses to suggest what to work on.
