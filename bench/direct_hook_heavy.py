#!/usr/bin/env python3
"""Direct Python hook with heavy imports — simulates a real-world hook."""
import json, sys
# Simulate realistic hook that needs libraries
import ast
import email
import xml.etree.ElementTree as ET
import urllib.parse
import http.client
import logging
import csv
import sqlite3
import hashlib
import re
import pathlib
import datetime
import collections
import functools
import itertools
import typing

def handle(payload, ctx=None):
    """Hook that does a tiny bit of work."""
    data = json.dumps(payload)
    h = hashlib.sha256(data.encode()).hexdigest()[:8]
    return {"hash": h}

if __name__ == "__main__":
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    result = handle(payload)
    print(json.dumps({"ok": True, "result": result}))
