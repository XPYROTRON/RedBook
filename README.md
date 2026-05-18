# RedBook v5

RedBook is a desktop library manager for Linux (GTK4 + Libadwaita) that helps you track what you own, what you read, and what you want to read.

## Features and properties

- Shelf-based organization: All, Want to Read, Reading, Finished, Paused, Abandoned, Owned, Wishlist, and Red Books.
- Fast search across title, author, ISBN, tags, series, and publisher.
- Rich metadata editing:
  - title, author, ISBN, series, language, publisher, pages
  - publish year/date, description, personal notes, tags
  - reading shelf, start date, finished date, and 0–5 rating
- Book detail page with split layout for metadata, description, and personal notes.
- Dashboard cards with live counts by reading state (including “Finished This Year”).
- Backup and restore support via compressed RedBook backup files.
- CSV export for external reporting and migration.
- Local cover image library with downloaded covers and persistent storage.
- Collapsible sidebar and responsive card grid.
- Password lock support:
  - set/change app password
  - disable password lock from the app menu
  - lock the app from the menu
  - unlock required when a password exists
- Metadata auto-load:
  - Open Library for core metadata
  - Goodreads search parsing for rating and cover preference (when available)
- Ubuntu-friendly packaging:
  - `.deb` installer provided
  - desktop launcher file
  - SVG app icon and AppStream metadata

Install:

```bash
sudo apt install ./redbook_0.6.0_all.deb
```
