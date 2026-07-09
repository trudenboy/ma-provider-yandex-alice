---
id: "0001"
title: "Borrow the Yandex account from a linked Yandex Music provider"
size: S
status: inprogress
priority: P1
effort_minutes: 10
feature_id:
---

## Problem Statement

Users who already run the Yandex Music provider must sign into Yandex a
second time to let this plugin register/manage a dialog skill: the
Authorization step runs its own Device Flow and caches its own x_token.

## Solution Summary

A "Yandex account source" dropdown in the Authorization block (same option
the Station and Ynison providers offer): pick a configured Yandex Music
instance to borrow its x_token, or keep "Use own credentials". When
borrowing, the Sign-in/Sign-out actions disappear, skill actions run on the
borrowed token read-only (never persisted into this plugin's config, never
rotated), and a rejected borrowed token surfaces "re-authenticate the
Yandex Music provider" instead of silently falling back to an own sign-in.

## Acceptance Criteria

1. The Authorization block shows the source dropdown listing every
   configured Yandex Music instance plus "Use own credentials (default)";
   a stale selection normalizes back to own.
2. With a source selected, the Sign-in and Sign-out actions are not
   rendered; a label explains authentication is managed in Yandex Music.
3. Skill actions (create/rename/update) use the borrowed x_token; the
   plugin's own `auth_x_token` storage stays empty while borrowing.
4. A linked instance that is not loaded / holds no x_token renders an
   actionable error in the Authorization block instead of breaking the
   form.
5. With "Use own credentials", behavior is byte-identical to today.

## Test Plan

- `test_dropdown_lists_instances_and_own` — options and default.
- `test_borrowing_hides_sign_in_and_out` — no ACTION entries, label shown.
- `test_borrowed_token_feeds_actions_and_is_not_persisted` — dispatcher
  sees the YM x_token; `values[auth_x_token]` stays empty.
- `test_borrow_source_error_is_rendered_not_raised` — form renders with an
  alert when the YM instance is missing.
- `test_stale_selection_normalizes_to_own` — removed instance → own mode.
