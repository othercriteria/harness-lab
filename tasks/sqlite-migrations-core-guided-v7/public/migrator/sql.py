import re
import sqlite3


def split_sql(sql):
    """Split complete SQLite statements, including triggers and quoted semicolons.

    Non-comment SQL must end with a semicolon. Empty/comment-only scripts are invalid.
    This existing helper may be reused by the transactional engine.
    """
    result, buffer = [], ""
    for char in sql:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            result.append(buffer)
            buffer = ""
    residue = re.sub(r"--[^\n]*(?:\n|$)|/\*.*?\*/", "", buffer, flags=re.S)
    if residue.strip() or not result:
        raise ValueError("incomplete or empty SQL script")
    return result
