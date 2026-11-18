def iter_records(fetch_page):
    cursor = None
    seen = set()
    while True:
        if cursor in seen:
            raise ValueError("Repeated pagination cursor")
        seen.add(cursor)
        page = fetch_page(cursor)
        yield from page.items
        if page.next_cursor is None:
            return
        cursor = page.next_cursor
