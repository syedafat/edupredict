# WP-02B Verification Report: Support Ticket Authorization

**Status:** Verified on 2026-09-29

## Scope

- Students can list, view, and reply only to tickets they created.
- Teachers can access tickets created by themselves or students in their assigned courses.
- Analysts can access tickets created by themselves or students in their authorized scope.
- Administrators retain institutional access and are the only role that can change ticket status.
- Ticket responses and status changes enforce object-level authorization.

## Evidence

Regression cases in `tests/test_wp02b_support_authorization.py` verify that a student can reply without changing status, another student's ticket is hidden (404), and an analyst cannot view a ticket outside the authorized student scope.

## Results

- Focused WP-02 authorization pytest set: **PASS**.
- Full pytest suite: **PASS**, 47 tests.
- unittest discovery rooted at `tests`: **PASS**, 20 tests.

## Limitations

- Teacher assigned-course ticket access is implemented through active course enrollments, but was not exercised against a live institutional database.
