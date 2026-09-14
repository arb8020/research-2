# How to Test

Source: https://matklad.github.io/2021/05/31/how-to-test.html
Author: matklad
Date: May 31, 2021

---

## Core Problems and Solutions

### Test Driven Design Ossification

When tests tightly couple to specific APIs, refactoring becomes costly. The solution involves creating a single `check` function that encapsulates the system under test:

```rust
#[track_caller]
fn check(
  input_haystack: &[i32],
  input_needle: i32,
  expected_result: bool,
) {
  let actual_result =
    binary_search(input_haystack, &input_needle).is_ok();
  assert_eq!(expected_result, actual_result);
}
```

**Key principle**: "keep an eye on tests standing in a way of refactors. Use the `check` idiom to make tests resilient to changes."

### Test Friction

Low friction for adding tests encourages more thorough coverage. Minimize boilerplate and cognitive barriers to testing.

### Test Features, Not Code

The "neural network test" provides a useful heuristic: **Could the test suite remain valid if the entire implementation were replaced by an opaque neural network?**

This approach tests observable behavior rather than internal mechanisms, making tests resilient to implementation changes.

### Making Tests Fast

Performance doesn't primarily depend on code volume. The real culprits are:
- Input/Output operations
- Outlier slow tests
- Excessively large inputs

**Solution**: "architecture the software to keep as much as possible sans io." Separate computation from I/O, allowing pure functions to be tested quickly even when complex.

## Data-Driven Testing Approach

The author advocates moving from interface-focused to data-focused testing. This enables:

- **Serialization**: Complex inputs specified in JSON, plain text, or embedded DSLs
- **Reusability**: Test suites work across different implementations
- **Maintainability**: Centralized test format reduces coupling

Example from rust-analyzer's "Goto Definition" tests uses a structured text format where `$0` marks cursor position and `^^^` marks expected results—a single test processes an entire multi-file project in milliseconds.

## Advanced Techniques

### Expect Tests

Rather than asserting values inline, store expected results as test data. A special test mode updates these expectations in-place when behavior changes correctly. Tools: `insta`, `k9`, `expect-test`.

### Observability for Hidden Properties

When testing non-observable properties (like cache hits), add logging or "coverage marks" as part of the system output, making them observable during testing.

### Externalized Tests

Move test case definitions into external files, forcing data-driven design and enabling cross-language test reuse. Trade-off: reduced IDE integration.

### Beyond Example-Based Testing

- **Property-based testing**: Generate random inputs and verify output properties
- **Full coverage testing**: Exhaustively check all inputs within a bounded range
- **Coverage-guided fuzzing**: Use random bytes with branch tracking to find edge cases
- **Structured fuzzing**: Generate syntactically valid random inputs

## Architectural Considerations

### Layers and Testing

Test each architectural layer independently:
```
L1 ← Tests
L1 ← L2 ← Tests
L1 ← L2 ← L3 ← Tests
L1 ← L2 ← L3 ← L4 ← Tests
```

This avoids recompiling entire dependency chains when modifying lower layers.

### Concurrency Challenges

The API `fn do_stuff_in_background(p: Param)` is untestable because it provides no way to synchronize with completion. Solution: "don't do this." Adopt structured concurrency patterns instead of fire-and-forget threading.

### External World Integration

When I/O is unavoidable (as with Cargo), accept slower tests and focus on:
- Reliable release processes
- Non-exceptional patch procedures
- Separate integration from core logic

## Using Tests Beyond Testing

The author documents using `#[test]` for:
- Code formatting verification
- Git history checks
- Documentation collection and validation
- License compatibility verification
- Performance regression detection (synthetic file sizing with linear regression)

## Process: Use Bors

Implement the "not rocket science rule"—a bot ensuring the merge commit passes all tests before advancing the main branch. This maintains pressure on test suite performance and prevents flaky test accumulation.

## Key Takeaways

1. Abundant testing advice often isn't actionable
2. Test ease-of-change is the primary quality metric
3. Test observable features, not implementation details
4. I/O and IPC dominate test performance, not code volume
5. Underutilized techniques: expectation tests, coverage marks, externalized tests
6. Overrepresented techniques: fluent assertions, mocks, BDD
7. Data-centric thinking unlocks better test design
8. Good test suites aid large-scale architectural clarity

## References

The article links to foundational resources including Gary Bernhardt's "Boundaries" talk, structured concurrency principles, and various testing libraries and practices across languages.
