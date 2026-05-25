# TDD Implementation Guide

Execute strict RED-GREEN-REFACTOR cycles. Every line of production code must be
justified by a failing test.

## The Cycle

**RED**: Write a failing test that describes the desired behavior. Run it. Confirm
it fails for the right reason — not a syntax error or import issue.

**GREEN**: Write the minimum code to make the test pass. Resist the urge to
generalize or optimize. Hardcode if that's the simplest path.

**REFACTOR**: Clean up while all tests stay green. Remove duplication, improve
names, extract methods. Revert immediately if any test breaks.

## Principles

- One behavior per test. The test name should read as a specification.
- Arrange-Act-Assert structure. Each section clearly separated.
- Test the interface, not the implementation. Tests should survive refactoring.
- Minimum 80% coverage target. 85%+ recommended.
- DAMP over DRY in test code. Duplication that makes intent obvious beats abstraction that hides it. Production code prizes DRY; tests prize Descriptive And Meaningful Phrases.

## Patterns

**Specification by Example**: Start with concrete input/output pairs, implement
to satisfy them, then generalize.

**Outside-In**: Write an acceptance test for the feature → implement the outer
layer → let failures drive inner layer design.

**Inside-Out**: Start with core domain logic tests → build outward to adapters
and interfaces.

## Edge Cases

Always cover: empty inputs, boundary values, error conditions, null/undefined,
concurrent access where relevant. Write these as separate RED-GREEN cycles,
not afterthoughts.

## Completion Criteria

- All tests pass
- No skipped or pending tests
- Coverage target met
- Refactoring complete — no obvious duplication or naming issues
