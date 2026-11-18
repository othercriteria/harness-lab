def iter_records(fetch_page):
    cursor = None
    while True:
        page = fetch_page(cursor)
        items = list(page.items)
        if not items:
            return
        yield from items
        if not page.next_cursor:
            return
        cursor = page.next_cursor
