#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GdkPixbuf, Gdk
import sqlite3, zipfile, json, csv, shutil, urllib.parse, html, hashlib
from pathlib import Path
from datetime import date, datetime

try:
    import requests
except Exception:
    requests = None

APP_ID = "io.github.XPYROTRON.RedBook"
APP_NAME = "RedBook"
DATA_DIR = Path.home() / ".local" / "share" / "redbook"
COVER_DIR = DATA_DIR / "covers"
DB_PATH = DATA_DIR / "redbook.sqlite3"

SHELVES = [
    ("All", "view-grid-symbolic"),
    ("Want to Read", "emblem-favorite-symbolic"),
    ("Reading", "media-playback-start-symbolic"),
    ("Finished", "emblem-ok-symbolic"),
    ("Paused", "media-playback-pause-symbolic"),
    ("Abandoned", "process-stop-symbolic"),
    ("Owned", "x-office-address-book-symbolic"),
    ("Wishlist", "starred-symbolic"),
    ("Red Books", "color-select-symbolic"),
]
SHELF_NAMES = [s[0] for s in SHELVES if s[0] != "All"]

CSS = b"""
.large-title { font-size: 24px; font-weight: 900; }
.stat-number { font-size: 22px; font-weight: 900; }
.stat-card { padding: 10px; border-radius: 16px; min-width: 130px; }
.book-card { padding: 8px; border-radius: 18px; min-width: 170px; }
.book-title { font-weight: 800; font-size: 14px; }
.stat-label { font-size: 12px; font-weight: 700; }
.detail-title { font-size: 30px; font-weight: 900; }
.section-title { font-size: 18px; font-weight: 800; }
.editor-cover-box { padding: 14px; border-radius: 20px; }
.editor-heading { font-size: 24px; font-weight: 900; }
"""

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COVER_DIR.mkdir(parents=True, exist_ok=True)

class Database:
    def __init__(self):
        ensure_dirs()
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.setup()

    def setup(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            isbn TEXT DEFAULT '',
            asin TEXT DEFAULT '',
            shelf TEXT DEFAULT 'Want to Read',
            series TEXT DEFAULT '',
            language TEXT DEFAULT '',
            publisher TEXT DEFAULT '',
            page_count INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            cover_path TEXT DEFAULT '',
            rating INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            categories TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            start_date TEXT DEFAULT '',
            finished_date TEXT DEFAULT '',
            first_publish_year TEXT DEFAULT '',
            openlibrary_key TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
        """)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
        """)
        columns = [r["name"] for r in self.conn.execute("PRAGMA table_info(books)").fetchall()]
        for col in ["first_publish_year", "openlibrary_key", "asin", "categories"]:
            if col not in columns:
                self.conn.execute(f"ALTER TABLE books ADD COLUMN {col} TEXT DEFAULT ''")
        self.conn.commit()

    def get_setting(self, key, default=""):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def books(self, text="", shelf="All"):
        clauses, params = [], []
        if shelf and shelf != "All":
            clauses.append("shelf=?"); params.append(shelf)
        if text:
            q = f"%{text}%"
            clauses.append("(title LIKE ? OR author LIKE ? OR isbn LIKE ? OR asin LIKE ? OR tags LIKE ? OR categories LIKE ? OR series LIKE ? OR publisher LIKE ?)")
            params += [q, q, q, q, q, q, q, q]
        sql = "SELECT * FROM books"
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC, title COLLATE NOCASE"
        return self.conn.execute(sql, params).fetchall()

    def get(self, book_id):
        return self.conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()

    def counts(self):
        rows = self.conn.execute("SELECT shelf, COUNT(*) c FROM books GROUP BY shelf").fetchall()
        d = {r["shelf"]: r["c"] for r in rows}
        d["All"] = sum(d.values())
        d["Finished This Year"] = self.conn.execute("SELECT COUNT(*) c FROM books WHERE finished_date LIKE ?", (f"{date.today().year}-%",)).fetchone()["c"]
        return d

    def save(self, data, book_id=None):
        now = datetime.now().isoformat(timespec="seconds")
        fields = ["title","author","isbn","asin","shelf","series","language","publisher","page_count","description","cover_path","rating","tags","categories","notes","start_date","finished_date","first_publish_year","openlibrary_key"]
        payload = {k: data.get(k, "") for k in fields}
        payload["page_count"] = int(payload["page_count"] or 0)
        payload["rating"] = int(payload["rating"] or 0)
        if book_id:
            payload["updated_at"] = now
            self.conn.execute("UPDATE books SET " + ",".join([f"{k}=?" for k in payload]) + " WHERE id=?", list(payload.values()) + [book_id])
        else:
            payload["created_at"] = now
            payload["updated_at"] = now
            self.conn.execute(f"INSERT INTO books ({','.join(payload)}) VALUES ({','.join(['?']*len(payload))})", list(payload.values()))
        self.conn.commit()

    def delete(self, book_id):
        self.conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        self.conn.commit()

    def backup(self, path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(DB_PATH, "redbook.sqlite3")
            z.writestr("manifest.json", json.dumps({"app": APP_NAME, "version": 4, "created_at": datetime.now().isoformat()}, indent=2))
            for p in COVER_DIR.glob("*"):
                if p.is_file(): z.write(p, f"covers/{p.name}")

    def restore(self, path):
        tmp = DATA_DIR / "_restore_tmp"
        if tmp.exists(): shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        with zipfile.ZipFile(path) as z: z.extractall(tmp)
        if not (tmp / "redbook.sqlite3").exists():
            raise RuntimeError("Invalid RedBook backup")
        self.conn.close()
        shutil.copy2(tmp / "redbook.sqlite3", DB_PATH)
        if (tmp / "covers").exists():
            COVER_DIR.mkdir(exist_ok=True)
            for p in (tmp / "covers").glob("*"):
                shutil.copy2(p, COVER_DIR / p.name)
        shutil.rmtree(tmp)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.setup()

    def export_csv(self, path):
        rows = self.conn.execute("SELECT * FROM books ORDER BY title COLLATE NOCASE").fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            if not rows: return
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            for r in rows: w.writerow(dict(r))

def clean_desc(v):
    return v.get("value", "") if isinstance(v, dict) else (v or "")

def safe_filename(text):
    return "".join(c for c in text.lower().replace(" ", "-") if c.isalnum() or c in "-_")[:96] or "book"

def download_cover(url, title):
    if not url or not requests: return ""
    try:
        r = requests.get(url, timeout=15)
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and r.content and ("image" in ctype or len(r.content) > 1000):
            path = COVER_DIR / f"{safe_filename(title)}-{int(datetime.now().timestamp())}.jpg"
            path.write_bytes(r.content)
            return str(path)
    except Exception:
        pass
    return ""

def fetch_metadata(query):
    if not requests:
        raise RuntimeError("python3-requests is missing.")
    query = query.strip()
    if not query:
        raise RuntimeError("Enter a title or ISBN.")
    compact = query.replace("-", "").replace(" ", "")
    isbn_like = compact.isdigit()
    asin_like = len(compact) == 10 and compact.isalnum()
    if isbn_like:
        r = requests.get(f"https://openlibrary.org/isbn/{urllib.parse.quote(query)}.json", timeout=15)
        if r.status_code != 200: raise RuntimeError("No Open Library ISBN result found.")
        d = r.json()
        authors = []
        for a in d.get("authors", [])[:4]:
            key = a.get("key")
            if key:
                ar = requests.get("https://openlibrary.org" + key + ".json", timeout=10)
                if ar.status_code == 200: authors.append(ar.json().get("name", ""))
        cover = d.get("covers", [None])[0] if d.get("covers") else None
        return {
            "title": d.get("title",""), "author": ", ".join([a for a in authors if a]),
            "isbn": query, "publisher": ", ".join(d.get("publishers", [])[:2]),
            "page_count": d.get("number_of_pages", 0) or 0,
            "description": clean_desc(d.get("description","")),
            "first_publish_year": d.get("publish_date",""),
            "openlibrary_key": d.get("works", [{}])[0].get("key","") if d.get("works") else "",
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" if cover else f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(query)}-L.jpg"
        }
    if asin_like:
        r = requests.get("https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode({"q": f"asin:{compact}", "maxResults": 1}), timeout=15)
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items:
                info = items[0].get("volumeInfo", {})
                ids = {i.get("type"): i.get("identifier") for i in info.get("industryIdentifiers", [])}
                image_links = info.get("imageLinks", {})
                return {
                    "title": info.get("title", ""),
                    "author": ", ".join(info.get("authors", [])[:4]),
                    "isbn": ids.get("ISBN_13") or ids.get("ISBN_10") or "",
                    "asin": compact,
                    "publisher": info.get("publisher", ""),
                    "page_count": info.get("pageCount", 0) or 0,
                    "description": info.get("description", ""),
                    "first_publish_year": info.get("publishedDate", ""),
                    "categories": ", ".join(info.get("categories", [])[:6]),
                    "openlibrary_key": "",
                    "cover_url": image_links.get("thumbnail", "").replace("http://", "https://"),
                }
        raise RuntimeError("No ASIN metadata found.")
    r = requests.get("https://openlibrary.org/search.json?" + urllib.parse.urlencode({"q": query, "limit": 1}), timeout=15)
    if r.status_code != 200: raise RuntimeError("Open Library search failed.")
    docs = r.json().get("docs", [])
    if not docs: raise RuntimeError("No matching book found.")
    d = docs[0]
    cover = d.get("cover_i")
    work_key = d.get("key", "")
    desc = ""
    if work_key:
        try:
            wr = requests.get("https://openlibrary.org" + work_key + ".json", timeout=10)
            if wr.status_code == 200:
                desc = clean_desc(wr.json().get("description",""))
        except Exception:
            pass
    return {
        "title": d.get("title",""), "author": ", ".join(d.get("author_name", [])[:4]),
        "isbn": d.get("isbn", [""])[0] if d.get("isbn") else "",
        "publisher": d.get("publisher", [""])[0] if d.get("publisher") else "",
        "page_count": d.get("number_of_pages_median", 0) or 0,
        "description": desc,
        "asin": "",
        "categories": ", ".join(d.get("subject", [])[:8]) if d.get("subject") else "",
        "first_publish_year": str(d.get("first_publish_year","") or ""),
        "openlibrary_key": work_key,
        "cover_url": f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" if cover else "",
    }

def fetch_goodreads_data(title, author=""):
    if not requests or not title.strip():
        return None
    try:
        q = f"{title} {author}".strip()
        u = "https://www.goodreads.com/search?" + urllib.parse.urlencode({"q": q, "search_type": "books"})
        r = requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        re = __import__("re")
        m = re.search(r'"averageRating":\s*([\d.]+)', r.text)
        rating = max(0, min(5, round(float(m.group(1))))) if m else None
        cm = re.search(r'<img[^>]+class="bookCover"[^>]+src="([^"]+)"', r.text) or re.search(r'"image"\s*:\s*"([^"]+)"', r.text)
        cover_url = cm.group(1).replace("\\/", "/") if cm else ""
        return {"rating": rating, "cover_url": cover_url, "source": "Goodreads"}
    except Exception:
        return {}

def img_for_path(path, w, h):
    if path and Path(path).exists():
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, True)
        except Exception:
            return None
    return None

class BookEditor(Adw.Window):
    __gsignals__ = {"saved": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, parent, db, book=None):
        super().__init__(transient_for=parent, modal=True)
        self.db, self.book = db, book
        self.cover_path = book["cover_path"] if book else ""
        self.openlibrary_key = book["openlibrary_key"] if book else ""
        self.set_title("Add Book" if not book else "Edit Book")
        self.set_default_size(980, 820)

        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)

        header = Adw.HeaderBar()
        load = Gtk.Button(label="Auto Load")
        load.set_icon_name("folder-download-symbolic")
        load.connect("clicked", self.lookup)
        save = Gtk.Button(label="Save")
        save.set_icon_name("document-save-symbolic")
        save.add_css_class("suggested-action")
        save.connect("clicked", self.save)
        header.pack_start(load)
        header.pack_end(save)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        outer.set_margin_top(22)
        outer.set_margin_bottom(24)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        scrolled.set_child(outer)
        root.append(scrolled)
        self.toast.set_child(root)

        title = Gtk.Label(label="Book details", xalign=0)
        title.add_css_class("editor-heading")
        outer.append(title)

        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        hero.set_hexpand(True)
        outer.append(hero)

        cover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        cover_box.add_css_class("editor-cover-box")
        cover_box.add_css_class("view")
        cover_box.set_valign(Gtk.Align.START)
        self.cover = Gtk.Image(pixel_size=240)
        self.cover.set_size_request(240, 350)
        cover_box.append(self.cover)
        hint = Gtk.Label(label="Cover is downloaded automatically when metadata is loaded.", wrap=True, xalign=0)
        hint.add_css_class("dim-label")
        hint.set_size_request(240, -1)
        cover_box.append(hint)
        hero.append(cover_box)

        form_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        form_col.set_hexpand(True)
        hero.append(form_col)

        basic = Adw.PreferencesGroup(title="Metadata")
        basic.set_hexpand(True)
        self.title = Adw.EntryRow(title="Title")
        self.author = Adw.EntryRow(title="Author")
        self.isbn = Adw.EntryRow(title="ISBN or search term")
        self.asin = Adw.EntryRow(title="ASIN")
        self.series = Adw.EntryRow(title="Series")
        self.language = Adw.EntryRow(title="Language")
        self.publisher = Adw.EntryRow(title="Publisher")
        self.pages = Adw.EntryRow(title="Page Count")
        self.year = Adw.EntryRow(title="First Published / Publish Date")
        self.tags = Adw.EntryRow(title="Tags")
        self.categories = Adw.EntryRow(title="Categories")
        for row in [self.title, self.author, self.isbn, self.asin, self.series, self.language, self.publisher, self.pages, self.year, self.tags, self.categories]:
            basic.add(row)
        form_col.append(basic)

        status = Adw.PreferencesGroup(title="Reading status")
        self.shelf = Adw.ComboRow(title="Shelf", model=Gtk.StringList.new(SHELF_NAMES))
        self.rating = Adw.ComboRow(title="Rating", model=Gtk.StringList.new(["0","1","2","3","4","5"]))
        self.start_date = Adw.EntryRow(title="Start Date YYYY-MM-DD")
        self.finished_date = Adw.EntryRow(title="Finished Date YYYY-MM-DD")
        for row in [self.shelf, self.rating, self.start_date, self.finished_date]:
            status.add(row)
        form_col.append(status)

        desc_group = Adw.PreferencesGroup(title="Book description")
        desc_frame = Gtk.Frame()
        desc_frame.set_hexpand(True)
        desc_frame.set_size_request(-1, 210)
        self.description = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.description.set_top_margin(12)
        self.description.set_bottom_margin(12)
        self.description.set_left_margin(12)
        self.description.set_right_margin(12)
        desc_frame.set_child(self.description)
        desc_group.add(desc_frame)
        outer.append(desc_group)

        notes_group = Adw.PreferencesGroup(title="My notes")
        notes_frame = Gtk.Frame()
        notes_frame.set_hexpand(True)
        notes_frame.set_size_request(-1, 210)
        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.notes.set_top_margin(12)
        self.notes.set_bottom_margin(12)
        self.notes.set_left_margin(12)
        self.notes.set_right_margin(12)
        notes_frame.set_child(self.notes)
        notes_group.add(notes_frame)
        outer.append(notes_group)

        if book:
            self.populate(book)
        else:
            self.shelf.set_selected(0)
            self.refresh_cover()

    def tv_get(self, tv):
        buf = tv.get_buffer()
        s, e = buf.get_bounds()
        return buf.get_text(s, e, True)

    def tv_set(self, tv, text):
        tv.get_buffer().set_text(text or "")

    def refresh_cover(self):
        pix = img_for_path(self.cover_path, 240, 350)
        if pix:
            self.cover.set_from_pixbuf(pix)
        else:
            self.cover.set_from_icon_name("x-office-address-book-symbolic")

    def populate(self, b):
        mapping = [
            ("title","title"),("author","author"),("isbn","isbn"),("series","series"),
            ("language","language"),("publisher","publisher"),("pages","page_count"),
            ("year","first_publish_year"),("tags","tags"),("categories","categories"),("asin","asin"),("start_date","start_date"),
            ("finished_date","finished_date")
        ]
        for attr, col in mapping:
            getattr(self, attr).set_text(str(b[col] or ""))
        self.tv_set(self.description, b["description"])
        self.tv_set(self.notes, b["notes"])
        self.shelf.set_selected(SHELF_NAMES.index(b["shelf"]) if b["shelf"] in SHELF_NAMES else 0)
        self.rating.set_selected(max(0, min(5, int(b["rating"] or 0))))
        self.refresh_cover()

    def lookup(self, *_):
        try:
            q = self.isbn.get_text().strip() or self.title.get_text().strip()
            meta = fetch_metadata(q)
            for k, widget in [
                ("title", self.title), ("author", self.author), ("isbn", self.isbn),
                ("asin", self.asin), ("categories", self.categories), ("publisher", self.publisher), ("first_publish_year", self.year)
            ]:
                if meta.get(k):
                    widget.set_text(str(meta[k]))
            if meta.get("page_count"):
                self.pages.set_text(str(meta["page_count"]))
            if meta.get("description"):
                self.tv_set(self.description, meta["description"])
            self.openlibrary_key = meta.get("openlibrary_key", "")
            gr = fetch_goodreads_data(meta.get("title", "") or self.title.get_text(), meta.get("author", "") or self.author.get_text())
            if gr.get("rating") is not None:
                self.rating.set_selected(gr["rating"])
            cover = download_cover(gr.get("cover_url") or meta.get("cover_url", ""), meta.get("title") or self.title.get_text() or "book")
            if cover:
                self.cover_path = cover
                self.refresh_cover()
                self.toast.add_toast(Adw.Toast(title="Metadata loaded (Goodreads cover/rating + Open Library details)"))
            else:
                self.toast.add_toast(Adw.Toast(title="Metadata loaded; no cover found"))
        except Exception as e:
            self.toast.add_toast(Adw.Toast(title=str(e)))

    def save(self, *_):
        if not self.title.get_text().strip():
            self.toast.add_toast(Adw.Toast(title="Title is required"))
            return
        data = {
            "title": self.title.get_text().strip(),
            "author": self.author.get_text().strip(),
            "isbn": self.isbn.get_text().strip(),
            "asin": self.asin.get_text().strip(),
            "shelf": SHELF_NAMES[self.shelf.get_selected()],
            "series": self.series.get_text().strip(),
            "language": self.language.get_text().strip(),
            "publisher": self.publisher.get_text().strip(),
            "page_count": self.pages.get_text().strip() or "0",
            "description": self.tv_get(self.description),
            "cover_path": self.cover_path,
            "rating": self.rating.get_selected(),
            "tags": self.tags.get_text().strip(),
            "categories": self.categories.get_text().strip(),
            "notes": self.tv_get(self.notes),
            "start_date": self.start_date.get_text().strip(),
            "finished_date": self.finished_date.get_text().strip(),
            "first_publish_year": self.year.get_text().strip(),
            "openlibrary_key": self.openlibrary_key,
        }
        self.db.save(data, self.book["id"] if self.book else None)
        self.emit("saved")
        self.close()

class DetailPage(Adw.Window):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, parent, db, book_id):
        super().__init__(transient_for=parent, modal=True)
        self.db, self.book_id = db, book_id
        self.set_title("Book Details")
        self.set_default_size(1180, 820)
        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)
        self.build()

    def label(self, txt, cls=None, wrap=True):
        l = Gtk.Label(label=txt or "", xalign=0, wrap=wrap, selectable=True)
        if cls:
            l.add_css_class(cls)
        return l

    def section_card(self, title, text):
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        wrapper.set_vexpand(True)
        wrapper.append(self.label(title, "section-title"))
        sc = Gtk.ScrolledWindow()
        sc.set_min_content_height(220)
        sc.set_vexpand(True)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        card.add_css_class("card")
        card.add_css_class("view")
        card.append(self.label(text))
        sc.set_child(card)
        wrapper.append(sc)
        return wrapper

    def build(self):
        b = self.db.get(self.book_id)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        edit = Gtk.Button(label="Edit")
        edit.set_icon_name("document-edit-symbolic")
        edit.connect("clicked", self.edit)
        done = Gtk.Button(label="Mark Finished")
        done.set_icon_name("emblem-ok-symbolic")
        done.connect("clicked", self.mark_finished)
        delete = Gtk.Button(label="Delete")
        delete.set_icon_name("user-trash-symbolic")
        delete.add_css_class("destructive-action")
        delete.connect("clicked", self.delete)
        header.pack_start(delete)
        header.pack_end(done)
        header.pack_end(edit)
        root.append(header)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(420)
        paned.set_vexpand(True)
        root.append(paned)
        self.toast.set_child(root)

        left_sc = Gtk.ScrolledWindow()
        left_sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        left_sc.set_child(left)
        paned.set_start_child(left_sc)

        pix = img_for_path(b["cover_path"], 300, 440)
        img = Gtk.Image(pixel_size=300)
        img.set_size_request(300, 440)
        if pix:
            img.set_from_pixbuf(pix)
        else:
            img.set_from_icon_name("x-office-address-book-symbolic")
        left.append(img)

        left.append(self.label(b["title"], "detail-title"))
        left.append(self.label("by " + (b["author"] or "Unknown author"), "title-3"))
        stars = "★" * int(b["rating"] or 0) + "☆" * (5 - int(b["rating"] or 0))
        left.append(self.label(f"{b['shelf']}  ·  {stars}", "dim-label"))

        meta = []
        for label, col in [("Series", "series"), ("Publisher", "publisher"), ("Published", "first_publish_year"), ("Language", "language"), ("Pages", "page_count"), ("ISBN", "isbn"), ("ASIN", "asin"), ("Started", "start_date"), ("Finished", "finished_date")]:
            val = b[col]
            if val:
                meta.append(f"<b>{html.escape(label)}:</b> {html.escape(str(val))}")
        ml = Gtk.Label(xalign=0, wrap=True, use_markup=True, selectable=True)
        ml.set_markup("\n".join(meta) if meta else "No metadata yet.")
        left.append(ml)
        for title, value in [("Categories", b["categories"]), ("Tags", b["tags"])]:
            if value:
                exp = Gtk.Expander(label=title)
                exp.set_expanded(False)
                exp.set_child(self.label(value, "dim-label"))
                left.append(exp)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        right.set_vexpand(True)
        paned.set_end_child(right)
        right.append(self.section_card("Description", b["description"] or "No description yet. Click Edit → Auto Load."))
        right.append(self.section_card("My Notes", b["notes"] or "No notes yet."))

    def edit(self, *_):
        d = BookEditor(self, self.db, self.db.get(self.book_id))
        d.connect("saved", lambda *_: (self.emit("changed"), self.close()))
        d.present()

    def mark_finished(self, *_):
        b = dict(self.db.get(self.book_id))
        b["shelf"] = "Finished"
        b["finished_date"] = date.today().isoformat()
        self.db.save(b, self.book_id)
        self.emit("changed")
        self.close()

    def delete(self, *_):
        self.db.delete(self.book_id)
        self.emit("changed")
        self.close()

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.db = Database()
        self.current_shelf = "All"
        self.sidebar_visible = True
        self.set_title(APP_NAME)
        self.set_default_size(1280, 820)
        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)

        header = Adw.HeaderBar()
        self.sidebar_btn = Gtk.ToggleButton()
        self.sidebar_btn.set_icon_name("sidebar-show-symbolic")
        self.sidebar_btn.set_active(True)
        self.sidebar_btn.connect("toggled", self.toggle_sidebar)
        header.pack_start(self.sidebar_btn)

        title = Gtk.Label(label="RedBook")
        title.add_css_class("title-1")
        header.set_title_widget(title)

        add = Gtk.Button(label="Add Book")
        add.set_icon_name("list-add-symbolic")
        add.add_css_class("suggested-action")
        add.connect("clicked", self.add_book)
        header.pack_end(add)

        self.search_visible = False
        self.search_toggle = Gtk.Button(icon_name="system-search-symbolic")
        self.search_toggle.set_tooltip_text("Show search")
        self.search_toggle.connect("clicked", self.toggle_search)
        header.pack_end(self.search_toggle)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Backup Library", "app.backup")
        menu.append("Restore Backup", "app.restore")
        menu.append("Export CSV", "app.exportcsv")
        menu.append("Lock App", "app.lock")
        menu.append("Set/Change Password", "app.setpassword")
        menu.append("Disable Password Lock", "app.disablepassword")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(header)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_position(270)
        self.paned.set_vexpand(True)
        root.append(self.paned)
        self.toast.set_child(root)

        self.sidebar_sc = Gtk.ScrolledWindow()
        self.sidebar_sc.set_size_request(260, -1)
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar.connect("row-selected", self.shelf_selected)
        self.sidebar_sc.set_child(self.sidebar)
        self.paned.set_start_child(self.sidebar_sc)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=16, margin_bottom=16, margin_start=18, margin_end=18)
        self.paned.set_end_child(content)

        self.search = Gtk.SearchEntry(placeholder_text="Search books, authors, ISBN/ASIN, tags, categories, series")
        self.search.connect("search-changed", lambda *_: self.refresh_library())
        self.search.set_visible(False)
        content.append(self.search)
        self.search.connect("activate", lambda *_: self.refresh_library())

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.dashboard = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8)
        self.dashboard.set_min_children_per_line(1)
        self.dashboard.set_max_children_per_line(12)
        self.dashboard.set_homogeneous(True)
        self.dashboard.set_hexpand(True)
        content.append(self.dashboard)

        lib_title = Gtk.Label(label="Library", xalign=0)
        lib_title.add_css_class("large-title")
        content.append(lib_title)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=14, row_spacing=14)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(12)
        self.flow.set_homogeneous(True)
        self.flow.set_hexpand(True)
        sc = Gtk.ScrolledWindow()
        sc.set_child(self.flow)
        sc.set_hexpand(True)
        sc.set_vexpand(True)
        content.append(sc)
        self.refresh_all()

    def toggle_sidebar(self, button):
        self.sidebar_visible = button.get_active()
        self.sidebar_sc.set_visible(self.sidebar_visible)
        self.paned.set_position(270 if self.sidebar_visible else 0)

    def toggle_search(self, _button):
        self.search_visible = not self.search_visible
        self.search.set_visible(self.search_visible)
        self.search_toggle.set_tooltip_text("Hide search" if self.search_visible else "Show search")
        if self.search_visible:
            self.search.grab_focus()
        else:
            self.search.set_text("")
            self.refresh_library()

    def on_key_pressed(self, _controller, keyval, _keycode, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.META_MASK):
            return False
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and ch.isprintable() and not ch.isspace():
            if not self.search.get_visible():
                self.toggle_search(self.search_toggle)
                self.search.set_text(ch)
            else:
                self.search.set_text(self.search.get_text() + ch)
            self.search.set_position(-1)
            self.search.grab_focus()
            return True
        return False

    def refresh_all(self):
        self.refresh_sidebar()
        self.refresh_dashboard()
        self.refresh_library()

    def refresh_sidebar(self):
        while (child := self.sidebar.get_first_child()):
            self.sidebar.remove(child)
        counts = self.db.counts()
        selected_row = None
        for shelf, icon in SHELVES:
            row = Gtk.ListBoxRow()
            row.shelf = shelf
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=9, margin_bottom=9, margin_start=12, margin_end=12)
            box.append(Gtk.Image(icon_name=icon, pixel_size=18))
            label = Gtk.Label(label=shelf, xalign=0, hexpand=True)
            count = Gtk.Label(label=str(counts.get(shelf, 0)), xalign=1)
            count.add_css_class("dim-label")
            box.append(label)
            box.append(count)
            row.set_child(box)
            self.sidebar.append(row)
            if shelf == self.current_shelf:
                selected_row = row
        if selected_row:
            self.sidebar.select_row(selected_row)

    def shelf_selected(self, _box, row):
        if row:
            self.current_shelf = row.shelf
            self.refresh_library()

    def refresh_dashboard(self):
        while (child := self.dashboard.get_first_child()):
            self.dashboard.remove(child)
        counts = self.db.counts()
        cards = [
            ("All", counts.get("All",0), "view-grid-symbolic", "All"),
            ("Want", counts.get("Want to Read",0), "emblem-favorite-symbolic", "Want to Read"),
            ("Reading", counts.get("Reading",0), "media-playback-start-symbolic", "Reading"),
            ("Finished", counts.get("Finished",0), "emblem-ok-symbolic", "Finished"),
            ("This Year", counts.get("Finished This Year",0), "office-calendar-symbolic", "Finished"),
            ("Red Books", counts.get("Red Books",0), "color-select-symbolic", "Red Books"),
        ]
        for label, value, icon, target in cards:
            btn = Gtk.Button()
            btn.add_css_class("flat")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.add_css_class("stat-card")
            box.add_css_class("view")
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            top.append(Gtk.Image(icon_name=icon, pixel_size=16))
            lab = Gtk.Label(label=label, xalign=0)
            lab.add_css_class("stat-label")
            top.append(lab)
            num = Gtk.Label(label=str(value), xalign=0)
            num.add_css_class("stat-number")
            box.append(top)
            box.append(num)
            btn.set_child(box)
            btn.connect("clicked", lambda _b, s=target: self.set_shelf(s))
            self.dashboard.append(btn)

    def set_shelf(self, shelf):
        self.current_shelf = shelf
        self.refresh_all()

    def refresh_library(self):
        while (child := self.flow.get_first_child()):
            self.flow.remove(child)
        books = self.db.books(self.search.get_text().strip(), self.current_shelf)
        if not books:
            empty = Gtk.Label(label="No books here yet. Click “Add Book” to start.", xalign=0)
            empty.add_css_class("dim-label")
            self.flow.append(empty)
            return
        for b in books:
            self.flow.append(self.book_card(b))

    def book_card(self, b):
        btn = Gtk.Button()
        btn.add_css_class("flat")
        btn.set_hexpand(True)
        btn.connect("clicked", lambda *_: self.open_detail(b["id"]))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        card.add_css_class("book-card")
        card.add_css_class("view")
        img = Gtk.Image(pixel_size=160)
        img.set_size_request(160, 190)
        pix = img_for_path(b["cover_path"], 160, 190)
        if pix:
            img.set_from_pixbuf(pix)
        else:
            img.set_from_icon_name("x-office-address-book-symbolic")
        title = Gtk.Label(label=b["title"] or "Untitled", xalign=0, wrap=True, lines=2)
        title.add_css_class("book-title")
        author = Gtk.Label(label=b["author"] or "Unknown author", xalign=0, wrap=True, lines=1)
        author.add_css_class("dim-label")
        meta_text = b["shelf"]
        if b["finished_date"]:
            meta_text += " · " + b["finished_date"]
        rating = int(b["rating"] or 0)
        if rating:
            meta_text += " · " + ("★" * rating)
        meta = Gtk.Label(label=meta_text, xalign=0, wrap=True, lines=2)
        meta.add_css_class("caption")
        card.append(img)
        card.append(title)
        card.append(author)
        card.append(meta)
        btn.set_child(card)
        return btn

    def open_detail(self, book_id):
        d = DetailPage(self, self.db, book_id)
        d.connect("changed", lambda *_: self.refresh_all())
        d.present()

    def add_book(self, *_):
        d = BookEditor(self, self.db)
        d.connect("saved", lambda *_: self.refresh_all())
        d.present()

    def choose_save(self, title, name, cb):
        d = Gtk.FileDialog(title=title, initial_name=name)
        d.save(self, None, lambda dialog, res: self._save_done(dialog, res, cb))

    def _save_done(self, dialog, res, cb):
        try:
            f = dialog.save_finish(res)
            if f:
                cb(Path(f.get_path()))
        except Exception as e:
            self.toast.add_toast(Adw.Toast(title=str(e)))

    def choose_open(self, title, cb):
        d = Gtk.FileDialog(title=title)
        d.open(self, None, lambda dialog, res: self._open_done(dialog, res, cb))

    def _open_done(self, dialog, res, cb):
        try:
            f = dialog.open_finish(res)
            if f:
                cb(Path(f.get_path()))
        except Exception as e:
            self.toast.add_toast(Adw.Toast(title=str(e)))

class RedBookApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, fn in [("backup", self.backup), ("restore", self.restore), ("exportcsv", self.export_csv), ("lock", self.lock_app), ("setpassword", self.set_password), ("disablepassword", self.disable_password)]:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", fn)
            self.add_action(act)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
            self._unlock_if_needed(win)
        win.present()

    def _hash_password(self, text):
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    def _ask_password(self, parent, title, callback):
        dialog = Adw.Window(transient_for=parent, modal=True, title=title)
        dialog.set_default_size(360, 120)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        row = Adw.PasswordEntryRow(title="Password")
        box.append(row)
        btn = Gtk.Button(label="Confirm")
        btn.add_css_class("suggested-action")
        box.append(btn)
        dialog.set_content(box)
        btn.connect("clicked", lambda *_: (callback(row.get_text().strip()), dialog.close()))
        dialog.present()

    def _unlock_if_needed(self, win):
        pw_hash = win.db.get_setting("lock_password_hash")
        if not pw_hash:
            return
        win.set_sensitive(False)
        def check(pw):
            if self._hash_password(pw) == pw_hash:
                win.set_sensitive(True)
                win.toast.add_toast(Adw.Toast(title="Unlocked"))
            else:
                win.toast.add_toast(Adw.Toast(title="Wrong password"))
                self._unlock_if_needed(win)
        self._ask_password(win, "Unlock RedBook", check)

    def backup(self, *_):
        w = self.props.active_window
        w.choose_save("Save RedBook Backup", f"redbook-{date.today().isoformat()}.redbook-backup", lambda p: (w.db.backup(p), w.toast.add_toast(Adw.Toast(title="Backup saved"))))

    def restore(self, *_):
        w = self.props.active_window
        def do_restore(p):
            w.db.restore(p)
            w.refresh_all()
            w.toast.add_toast(Adw.Toast(title="Backup restored"))
        w.choose_open("Restore RedBook Backup", do_restore)

    def export_csv(self, *_):
        w = self.props.active_window
        w.choose_save("Export CSV", f"redbook-{date.today().isoformat()}.csv", lambda p: (w.db.export_csv(p), w.toast.add_toast(Adw.Toast(title="CSV exported"))))

    def set_password(self, *_):
        w = self.props.active_window
        def save_pw(pw):
            if len(pw) < 4:
                w.toast.add_toast(Adw.Toast(title="Password must be at least 4 chars"))
                return
            w.db.set_setting("lock_password_hash", self._hash_password(pw))
            w.toast.add_toast(Adw.Toast(title="Password saved"))
        self._ask_password(w, "Set App Password", save_pw)

    def lock_app(self, *_):
        w = self.props.active_window
        w.set_sensitive(False)
        self._unlock_if_needed(w)

    def disable_password(self, *_):
        w = self.props.active_window
        if not w.db.get_setting("lock_password_hash"):
            w.toast.add_toast(Adw.Toast(title="Password lock is already disabled"))
            return
        w.db.set_setting("lock_password_hash", "")
        w.toast.add_toast(Adw.Toast(title="Password lock disabled"))

def main():
    return RedBookApp().run(None)

if __name__ == "__main__":
    raise SystemExit(main())
