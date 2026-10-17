# Problem browsing and PDF caching

Opening a Supabase statement PDF resolves metadata and checks visibility before
reading Storage. It must never call the full problem loader or download hidden
tests. Judging continues to use the full, hash-verified problem loader.

PDF responses use `Cache-Control: private, no-cache`, `Vary: Cookie` and a
content-based ETag. Browsers may retain bytes, but must revalidate before reuse;
visibility is checked before returning either 200 or 304. The Pages proxy does
not share-cache these responses. Existing visibility metadata TTLs still apply.

The bounded server PDF cache expires after 300 seconds. A metadata refresh
(normally every 30 seconds) also invalidates PDFs when a problem's `updated_at`
or `statement_pdf_path` changes, or the problem disappears. **When replacing a
Storage PDF, also update its problem row** so the metadata version changes.
Replacing only Storage bytes may keep the previous PDF until cache expiry.

The SPA shares in-flight detail requests between hover and navigation and reuses
details for 60 seconds. Identity changes clear that cache and prevent old
responses from populating it or rendering in a new session. This client cache
does not grant access to PDFs or submissions; those endpoints check visibility.

## Regression checks

These tests use versioned synthetic fixtures and fake Supabase, with no live DB:

```sh
python -m unittest discover -s tests -p test_problem_loading.py -v
node --test tests/test_problem_loading.js
```

The Python tests cover zero hidden-test downloads while browsing, numeric routes,
authorization before conditional responses, PDF invalidation independent of
test hashes, expiry, and full-test loading for judging. The JavaScript tests
cover deduplication, expiry/retry, identity changes and stale navigation responses.

For latency comparisons, measure the same public detail and PDF URLs from the
same browser/network before and after deployment. Record warm/cold cache state,
status, transferred bytes and request counts separately. A few samples are not
a population-wide latency guarantee.
