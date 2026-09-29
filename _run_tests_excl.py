"""One-off diagnostic runner: full suite minus the one test confirmed to
hang (test_casaquant_app.TestCasaQuantInApp.test_workbook_round_trip),
so the rest of the suite can be verified while that hang is looked at
separately. Not part of the test suite itself; delete after use.
"""
import sys
import unittest

EXCLUDE = {
    "test_casaquant_app.TestCasaQuantInApp.test_workbook_round_trip",
}


def test_id(t):
    return t.id().split(".", 1)[-1] if "." in t.id() else t.id()


def flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flatten(t)
        else:
            yield t


def build_filtered():
    discovered = unittest.defaultTestLoader.discover("tests")
    kept = unittest.TestSuite()
    skipped = []
    for t in flatten(discovered):
        tid = t.id()
        short = ".".join(tid.split(".")[-3:]) if tid.count(".") >= 2 else tid
        if short in EXCLUDE:
            skipped.append(tid)
            continue
        kept.addTest(t)
    return kept, skipped


if __name__ == "__main__":
    suite, skipped = build_filtered()
    print(f"Excluded {len(skipped)} known-hanging test(s): {skipped}")
    print(f"Running {suite.countTestCases()} tests...")
    sys.stdout.flush()
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
