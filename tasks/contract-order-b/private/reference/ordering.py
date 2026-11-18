from functools import cmp_to_key

def order_records(records, compare):
    return sorted(records, key=cmp_to_key(compare))
