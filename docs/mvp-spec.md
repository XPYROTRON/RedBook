# RedBook MVP Specification

## 1) Product goals

RedBook is an offline-first reading tracker with strong privacy defaults, focused on desktop Linux.

### Primary outcomes

- Fast local management of books and shelves.
- Minimal internet dependency (metadata + cover fetch only).
- Reliable backup and restore with user-visible preview.

## 2) Platform and UI stack

- **Platform:** Linux desktop
- **Toolkit:** GTK 4 + Libadwaita
- **Display server:** Wayland-compatible
- **Layout:** Responsive grid/list views
- **Theme:** Dark/light via Adwaita style manager

## 3) MVP features

### 3.1 Library and shelves

Shelves in MVP:

- Want to Read
- Reading
- Finished
- Paused
- Abandoned
- Owned
- Wishlist

Book fields in MVP:

- Title, subtitle (optional)
- Authors (1..n)
- ISBN-10/ISBN-13 (optional)
- Publisher (optional)
- Description (optional)
- Page count (optional)
- Language (optional)
- Format: physical / ebook / audiobook
- Tags (free-form)
- User rating
- Notes
- Quotes
- Private comments
- Red Book flag (boolean)

### 3.2 Metadata ingestion

Input methods:

- Search by title
- Search by author
- Search by ISBN

Sources:

- Open Library APIs
- Google Books APIs

Behavior:

- Attempt Open Library first, Google Books second, merge where practical.
- Always allow manual edits when metadata is incorrect.
- Track metadata source and fetch timestamp for debugging.

### 3.3 Cover cache

- Download and store covers in a local cache directory.
- Deduplicate by content hash (sha256).
- Keep DB pointer to active cover file path.
- Missing cover fallback uses generated placeholder.

### 3.4 Reading history

MVP tracking:

- Start date
- Finished date
- Multiple read-throughs per book
- Progress metric (pages or percent)
- Timestamped reading sessions

Derived stats:

- Books finished this year
- Pages read this year
- Average rating this year

### 3.5 Backup and restore

Export:

- Encrypted `.redbook-backup` archive (MVP required)
- JSON export (MVP optional but recommended)
- CSV export (MVP optional but recommended)
- Plain backup folder (database + covers)

Restore:

- Restore preview before overwrite (counts, date range, sample titles)
- Explicit confirmation to replace current data

## 4) Privacy model

- Offline-first local database
- Internet only for metadata/cover fetch
- User toggle: **Never connect automatically**
- Optional encrypted local database mode (post-MVP if schedule constrained)

## 5) Suggested local data model

## Core tables

- `books`
- `authors`
- `book_authors` (M:N)
- `shelves`
- `book_shelves` (M:N)
- `tags`
- `book_tags` (M:N)
- `readthroughs`
- `reading_sessions`
- `covers`
- `loans` (post-MVP)

## Key constraints

- Unique ISBN-13 where present.
- Soft duplicate detector on normalized title + first author.
- Immutable IDs (UUIDv4 or ULID).

## 6) App architecture (MVP)

- `ui/` GTK views, dialogs, controllers
- `core/` domain models and use-cases
- `data/` SQLite repository layer
- `integrations/` Open Library + Google Books clients
- `backup/` export/import + encryption
- `search/` local index and filtering

## 7) User flows

### Add book (fast path)

1. User clicks **Add Book**.
2. Enters title/author/ISBN.
3. App shows metadata matches.
4. User selects match, edits fields, chooses shelf.
5. App saves book locally and caches cover.

### Finish book

1. Open book details.
2. Set finished date.
3. Move shelf to Finished.
4. Stats update immediately.

### Restore backup

1. User selects backup file.
2. App decrypts and validates.
3. App shows preview summary.
4. User confirms overwrite.
5. App applies restore and reindexes.

## 8) Non-functional requirements

- Cold start under 2 seconds on average laptop.
- Search results under 100 ms for libraries up to 20k books.
- Zero telemetry by default.
- Clear error states for offline/timeout/API errors.

## 9) Post-MVP roadmap

- Barcode scanning
- Duplicate merge UI
- Series grouping + next-in-series reminders
- Lending tracker
- Attach photos of physical books
- Goodreads/StoryGraph CSV import
- Random pick from Want to Read
- Arabic/RTL note rendering enhancements
- App lock with password

## 10) Delivery milestones

1. **Milestone A:** Data model + CRUD + shelves
2. **Milestone B:** Metadata lookup + cover cache
3. **Milestone C:** Reading history + finished flow + stats
4. **Milestone D:** Backup/restore + encryption + QA polish
