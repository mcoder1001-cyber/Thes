# T5 prediction: snapshot uniqueness

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T5.

- Hooks off: start-up `Random.nextLong()`, `Math.random()` and the start-up token are
  identical in all 10 copies (1 distinct of 10). This is also the control.
- `UUID.randomUUID()` and `SecureRandom`: no prediction (the CRaC JDK may re-seed).
- `nanoTime` differs.
- Hooks on: **10 distinct of 10 for every field**.
