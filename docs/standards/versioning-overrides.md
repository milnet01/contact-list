# Versioning — Contact List's answers

This project follows `~/.claude/standards/versioning.md` in full. That standard
asks each project one question it cannot answer for them (§ 3): **what, if it
stopped working, makes a release breaking?** This file is that answer. It is not
a delta: nothing here overrides a rule.

The project is past `1.0`, so § 4's `1.0` exit condition does not apply.

## Breaking surfaces

A release that breaks any of these is a MAJOR bump.

- **The database.** A `contacts.db` written by an earlier 1.x release opens and
  migrates forward on the first launch. Migrations run forward only. Run from
  source, it lives beside the code as `contacts.db`; the downloadable builds
  keep it in the config folder below.
- **Exported files.** A vCard exported by an earlier 1.x release imports with
  nothing lost (the import/export spec's INV-2, held across versions). A CSV
  export's `Name, Type, Email, Phone, Notes` import back into those fields. The
  CSV columns — `Name, Type, Email, Phone, Notes, Created, Updated`, in that
  order — are what other tools read.
- **Environment variables.** `SECRET_KEY`, `CONTACT_LIST_DB`,
  `CONTACT_LIST_PORT`, `PORT` and `LWSM_MANAGED` keep their names and meaning.
- **The config folder.** `~/.config/contact-list/` and what it holds:
  `secret_key`, `credentials.json`, `token.json`, `photos/`,
  `contact-list.log`, and — in the downloadable builds — `contacts.db`.
- **The default address.** `http://127.0.0.1:5002`, and the GET page URLs in
  DESIGN.md §9 — people bookmark them. The POST routes are form targets on the
  app's own pages and are not surfaces.
- **Keyboard shortcuts.** `/` or `s` to search, `n` for a new contact, `Escape`
  to dismiss.
- **What sync writes to Google.** The set of fields the app manages on a
  person's Google contact (DESIGN.md §8.2's mapping table) — adding a field
  or dropping one is breaking, since either changes what sync overwrites —
  and that it never deletes a Google contact.
- **Release download names.** `Contact-List-x86_64.AppImage`,
  `Contact-List.exe` and `Contact-List.dmg`, which links and updaters point at.

## Not surfaces

Page layout, styling, wording, log-line format, and the internal Python API
change in any release.

A surface missing from this list is still a surface (§ 3): if users rely on it,
breaking it is breaking.
