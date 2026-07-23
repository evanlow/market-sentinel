# Prime Directive: Development Guidelines

**Last Updated:** July 23, 2026  
**Purpose:** Ensure high-quality, maintainable code by learning from past experiences and establishing best practices for all team members, AI agents, and contributors.

**Scope:** This directive is designed for use across all software projects. Project-specific case studies and stack/tool profiles are explicitly labeled as optional examples.

---

## 📋 Quick Reference - Before Every Commit

```markdown
Pre-Commit Checklist:
□ Virtual environment active (Principle 0)
□ Full regression suite passes (Principle 1)
□ No secrets or credentials in the diff (Principle 12)
□ Change is on a feature branch, not directly on main (Principle 13)

For Backend-Only Changes:
□ Tests added/updated for new code
□ All tests pass
□ Any strange behavior investigated (Principle 8)
→ Ready to commit

For UI Changes (HTML/CSS/JavaScript):
□ Backend tests passing
□ Manual smoke test completed (Principle 5)
□ Browser console checked (F12) - 0 errors
□ Critical user flows tested
□ Input validation: Frontend (UX) + Backend (Security) (Principle 7)
□ Any strange behavior investigated (Principle 8)
□ Manual testing documented in commit message
→ Ready to commit

Session Log Cadence (Mandatory):
□ Append `session_log.md` at start, each test run, each major implementation cycle, and handoff (include KPI delta)

Commit Message Format:
  <type>: <description>
  
  <body with details>
  
  Backend Tests: X/X passed, 0 warnings [PASS]
  Manual Testing: [PASS] (for UI changes only)
    - [What you tested]
    - [Results]

Approved ASCII replacements:
  [PASS]  == previously ✓
  [FAIL]  == previously ✗
  [OK]    == previously ✓
  [DONE]  == previously ✓
  [TODO]  == previously ?
  [WAIT]  == previously ⏳
  ->      == previously →
  -       == previously •
```

---

## 📊 Live Directive Compliance KPI (Session-Level)

Use a live compliance score throughout every working session to make adherence observable and auditable in real time.

### KPI Score Model

**Score format:** `X/8 green`

- **Green** = Requirement satisfied and evidenced in this session
- **Yellow** = Not yet applicable or pending the relevant step
- **Red** = Violated; must be flagged and corrected before continuing

### Required KPI Checklist (Track Live)

1. **Track directive compliance live**
2. **Verify venv before Python actions** (Principle 0)
3. **Confirm baseline tests pass clean** (Principle 1)
4. **Require post-change tests clean** (Principle 1)
5. **Enforce UI manual smoke checks** for UI changes (Principle 5)
6. **Validate input handling: Frontend (UX) + Backend (Security)** for form inputs (Principle 7)
7. **Investigate anomalies, don't work around them** (Principle 8)
8. **Record compliance status in updates**

### Session Reporting Protocol

- Report the KPI score in progress updates and handoffs
- Update checklist state immediately after each meaningful action
- If any item turns **Red**, stop new implementation work, fix the issue, then resume
- If an item is **Yellow**, state what trigger/action will move it to **Green**

### Checkpoint Cadence Rule (Mandatory)

Append an entry to `session_log.md` at the following minimum cadence:

1. **Session Start** - before implementation begins
2. **Environment/Test Gate** - after venv verification and baseline test run
3. **Each Major Implementation Cycle** - after meaningful code changes and their verification
4. **Every Test Execution** - when running targeted tests or full suite tests
5. **Any State Change to Red** - immediately when a violation is detected, plus correction outcome
6. **Session Handoff/Close** - final status and next steps

---

## 🎯 Core Principles

### 0. **Virtual Environment Verification - ALWAYS FIRST**
**CRITICAL:** Before ANY pip install, pytest, or Python execution, VERIFY you are in the virtual environment.

**The Protocol:**
1. ✅ **Check Python path** - run `python -c "import sys; print(sys.executable)"`
2. ✅ **Verify it points to project venv** - path should contain project venv path
3. ❌ **If using global Python** - activate venv first
4. ✅ **Re-verify after activation** - check Python path again to confirm activation worked

**CRITICAL - DO NOT CREATE NEW VENV WHEN ONE EXISTS:**
- Check for existing venv indicators FIRST (e.g., `.venv/`, `venv/`)
- If venv exists at project root, just activate it — don't create a new one

### 1. **100% Test Pass Rate + Zero Warnings - Non-Negotiable**
All tests must pass AND produce zero warnings before AND after ANY code changes. No exceptions.

**MANDATORY: Tests Must Exist Before Code Changes**
- ❌ **Never make code changes without test coverage**
- ✅ **Write tests FIRST for new features (TDD)**
- ✅ **Add tests IMMEDIATELY when fixing bugs**
- ❌ **Never commit untested code** - tests prevent regressions

**The Protocol:**
1. ✅ Verify baseline - run full test suite BEFORE any changes (zero failures, zero warnings)
2. 🔄 Make changes (one logical step at a time)
3. ✅ **Run tests IMMEDIATELY** after changes (zero failures, zero warnings)
4. ❌ If tests fail OR warnings appear - fix immediately or revert
5. ✅ Only commit when tests pass + manual verification complete (if UI changed)

**Warning Policy:**
- Warnings are NOT acceptable - they must be investigated and resolved
- Every warning indicates a potential issue (deprecations, type mismatches, anti-patterns)
- "Just warnings" become breaking errors in future versions
- Zero tolerance for warnings = clean, maintainable codebase

### 2. **Verify First, Code Second**  
Never assume how existing code works. Always verify before implementing.

**✅ Do:**
- Check existing code patterns before implementing
- Verify method signatures and return types
- Look for usage examples in tests

### 3. **Defensive Programming Always**  
Assume nothing. Handle None, validate inputs, check bounds.

**✅ Do:**
```python
position = self.get_position(symbol) or 0  # Default to 0 if None
if position <= 0:
    ...
```

### 4. **Test Incrementally, Not All At Once**  
Build and verify in small steps. Don't write 300 lines before testing.

### 5. **Frontend/UI Testing - The Backend Test Blind Spot**
**CRITICAL:** Backend tests (pytest, unittest) **CANNOT** catch frontend bugs. Know the gap.

**The Reality Check:**
- ✅ Backend tests verify: routes work, logic correct, data flows properly
- ❌ Backend tests **MISS**: JavaScript bugs, form behavior, UI interactions, browser rendering
- 🎯 **100% backend test pass ≠ working application from user perspective**

**The Protocol - Web Applications:**

**After ANY UI Change (HTML/CSS/JavaScript):**
1. ✅ **Run backend tests** - ensure server-side still works (100% pass required)
2. ✅ **Manual smoke test** - actually use the application (MANDATORY)
3. ✅ **Check browser console** - no JavaScript errors (F12 DevTools)
4. ✅ **Test critical user flows** - can users complete key tasks?
5. ✅ **Verify on refresh** - state persists, no unexpected resets

### 6. **User-Facing Output Quality - No Truncated Business Content**
**CRITICAL:** Do not ship user-facing documents with truncated sentences unless explicitly labeled as a preview.

### 7. **Enterprise Input Validation & Security Standards**
**CRITICAL:** Never trust frontend validation alone. Always validate and sanitize on the backend.

**The Golden Rules:**
1. **Frontend validation = UX convenience** (instant feedback, prevent network calls)
2. **Backend validation = Security boundary** (enforceable, cannot be bypassed)
3. **Both are required** - frontend for UX, backend for security

### 8. **Investigate Anomalies - Don't Work Around Them**
**CRITICAL:** If something seems wrong, strange, or requires a workaround - it IS wrong. Stop and investigate.

**The Rule:**
```
IF behavior seems unexpected OR requires a workaround:
  THEN:
    1. STOP forward progress immediately
    2. Document the strange behavior
    3. Investigate root cause thoroughly
    4. Fix properly OR confirm it's intentional
    5. ONLY THEN continue with your task
```

### 9. **AI Agent Execution Discipline — No Blind Commands**
**CRITICAL:** AI agents must never execute terminal commands blindly. Every command must be grounded, observable, and use the simplest possible tool for the job.

**Never Assume Paths:**
Before writing **any** path into a command (especially for output redirection), verify it exists.

### 10. **PowerShell + Python: Never Inline Complex Python via `-c`**
**CRITICAL:** PowerShell parses `{`, `}`, `'`, and `"` inside `-c "..."` strings before Python ever sees them.

**The Rule:** Never pass Python code that contains `{`, `}`, or nested quotes directly to `python -c "..."`. Write it to a `.py` file instead, run the file, then delete it.

### 11. **Mock Fidelity — Mocks Must Enforce the Real Interface**
**CRITICAL:** A mock that doesn't replicate the real class's contract gives false confidence. Tests pass; production crashes.

### 12. **Secrets & Credentials Management — Never Commit Secrets**
**CRITICAL:** Credentials, API keys, tokens, and passwords committed to version control are permanently exposed.

**The Rule:** Never commit secrets to version control. Ever. Not even temporarily.

**The Correct Pattern:**
```python
# ✅ CORRECT — load secrets from environment variables
import os
from dotenv import load_dotenv

load_dotenv()  # Loads from .env file (which is in .gitignore!)

API_KEY = os.environ["API_KEY"]
```

**Project Setup (Mandatory for every project):**
1. Create `.env` file for local secrets (never commit this)
2. Create `.env.example` with placeholder values (SAFE to commit)
3. Ensure `.gitignore` includes `.env`

### 13. **Git Branching & Code Review — Protect the Main Branch**
**CRITICAL:** Committing untested or unreviewed code directly to `main` bypasses quality gates.

**The Branching Model:**
```
main          ← production-ready only; never commit directly here
  └─ feature/my-feature     ← all new work starts here
  └─ fix/bug-description    ← bug fixes
  └─ chore/dependency-update ← maintenance tasks
```

**The Workflow (Non-Negotiable):**
1. **Create a feature branch** from up-to-date `main`
2. **Work on the branch** — commit frequently with descriptive messages
3. **Pass all tests locally** before opening a PR (Principle 1)
4. **Open a Pull Request** — describe what changed and why
5. **Code review** — at least one reviewer must approve before merge
6. **Merge** only after all checks pass and review is approved

### 14. **CDN / External Resource Integrity — Never Write SRI Hashes by Hand**
**CRITICAL:** Subresource Integrity (SRI) `integrity="sha384-..."` attributes must always be computed directly from the live CDN file.

---

## 🧪 Testing Strategy Decision Matrix

**Quick Guide: What Testing Do I Need?**

| Change Type | Backend Tests | Manual UI Test | E2E Browser Tests |
|-------------|--------------|----------------|-------------------|
| **Backend logic only** | ✅ Required | ❌ Not needed | ❌ Not needed |
| **UI only** (CSS, static HTML) | ⚠️ Run existing | ✅ Required | ❌ Not needed |
| **JavaScript/Forms** | ✅ Required | ✅ Required | ⚠️ Consider for complex |
| **Full-stack feature** | ✅ Required | ✅ Required | ⚠️ Consider for critical |
| **Bug fix** (any layer) | ✅ Add regression test | ✅ Required if UI | ❌ Usually not needed |

---

## 🔍 Pre-Implementation Checklist

Before writing ANY new code that uses existing classes/methods:

### ☑️ Research Phase (Mandatory)

1. **Check Method Signatures** - Use grep/search to find method definitions
2. **Verify Enum Values** - Read the enum definition
3. **Inspect Data Structures** - Check class attributes and properties
4. **Find Usage Examples** - See how others use this API

### ☑️ Before Calling Any Method

- [ ] Checked the method signature (parameters, types, order)
- [ ] Verified return type (can it be None? Optional?)
- [ ] Checked for required imports
- [ ] Looked for existing usage examples
- [ ] Understood parameter types (enum vs string, int vs Optional[int])

---

## 🚨 Common Pitfalls & Solutions

### Pitfall 1: Wrong Enum Values
**Problem:** Assuming enum names without checking
**Solution:** Always verify enum definitions

### Pitfall 2: Method Signature Mismatch
**Problem:** Implementing interface without checking base class
**Solution:** Check abstract method in base class

### Pitfall 3: Attribute Name Assumptions
**Problem:** Guessing attribute names
**Solution:** Check class definition

### Pitfall 4: None Type Errors
**Problem:** Not handling None return values
**Solution:** Always handle None explicitly

### Pitfall 5: Parameter Type Confusion
**Problem:** Passing string where enum expected
**Solution:** Use proper enum type

---

## 📋 Development Workflow (The Right Way™)

### Phase 1: Research (15-30% of time)
1. Understand the requirement
2. Find relevant existing code
3. Check base classes and interfaces
4. Verify data structures and enums
5. Look for usage examples
6. Document findings in comments

### Phase 2: Design (10-15% of time)
1. Sketch out the implementation
2. Identify dependencies
3. Plan for error handling
4. Consider edge cases
5. Keep it simple initially

### Phase 3: Implementation (40-50% of time)
1. Start with minimal working code
2. Match signatures exactly
3. Add defensive checks (None, bounds, types)
4. Use proper types (enums, not strings)
5. Add logging/print statements for debugging
6. Keep functions small and focused

### Phase 4: Testing (20-30% of time)
1. Test each component in isolation
2. Add unit tests as you go
3. Run tests frequently (after each component)
4. Fix errors immediately - don't accumulate
5. Verify integration works
6. Run full test suite before committing

---

## ✅ Code Quality Standards

### Type Safety
```python
# ✅ GOOD: Use type hints
def calculate_value(
    self, 
    symbol: str, 
    price: float,
    fraction: Optional[float] = None
) -> int:
    ...
```

### Error Handling
```python
# ✅ GOOD: Validate inputs
if not symbol or symbol not in self.config.symbols:
    return

# ✅ GOOD: Handle exceptions gracefully
try:
    result = risky_operation()
except SpecificError as e:
    log.warning(f"Operation failed: {e}")
    return default_value
```

---

## 🎯 Success Metrics

### Before Considering Code "Done"

- [ ] All unit tests passing (100%) - baseline verified with 0 warnings
- [ ] All unit tests passing (100%) - after changes verified with 0 warnings
- [ ] Zero compiler/linter warnings (all investigated and fixed)
- [ ] Zero test warnings (deprecations, type issues, etc. all resolved)
- [ ] No None-type errors
- [ ] All edge cases handled
- [ ] Code reviewed (by peer or self)
- [ ] Documentation complete
- [ ] Integration tested
- [ ] Performance acceptable
- [ ] Git commit with clear message including warning count

### Definition of "Done"

Code is only done when:
1. ✅ Baseline tests verified (before changes): X passed, 0 warnings
2. ✅ Changes implemented
3. ✅ Tests pass after changes (verify again): X passed, 0 warnings
4. ✅ Zero warnings (all warnings investigated and resolved)
5. ✅ Error handling complete
6. ✅ Integrated and verified
7. ✅ Documented
8. ✅ Committed with test count AND warning count

---

## 🤝 Team Expectations

### For All Team Members (Human & AI)

1. **Read this document before starting work**
2. **Follow the checklist - every time**
3. **Ask questions if unsure - don't guess**
4. **Test incrementally - don't batch**
5. **Fix errors immediately - don't defer**
6. **Document learnings - update this file**

### For AI Agents Specifically

1. **Always use verification tools before implementing**
2. **Never assume - always verify**
3. **Test each component before moving on**
4. **Read error messages completely and act on them**
5. **Keep implementations simple initially**
6. **Ask for clarification if requirements are ambiguous**

### For Code Reviewers

1. **Check that verification was done**
2. **Look for None handling**
3. **Verify test coverage**
4. **Ensure error handling present**
5. **Confirm documentation exists**

---

## 📚 Resources

### Internal Documentation
- `README.md` - Project overview
- `session_log.md` - Session-level compliance log and KPI checkpoints
- `tests/` - Living examples of expected behavior and usage patterns

### When in Doubt
1. Check existing tests - they show correct usage
2. Use grep/search to find patterns
3. Read the source code - it's the truth
4. Ask the team - collaboration over guessing

---

## 🔄 Document Maintenance

### When to Update This Document

- After encountering a new type of error
- When establishing a new pattern
- After team retrospectives
- When tooling changes
- Quarterly review minimum

### How to Update

1. Add specific examples
2. Keep it practical, not theoretical
3. Include code snippets
4. Update "Lessons Learned" section
5. Date the changes

---

## 💡 Remember

> **"100% test pass rate with zero warnings is not a goal - it's a requirement."**

> **"Warnings are errors waiting to happen - fix them immediately."**

> **"The best code is code that works correctly the first time because you took the time to verify before implementing."**

> **"Tests are not overhead - they're proof your code works."**

> **"Defensive programming isn't paranoia - it's professionalism."**

---

## Code Quality Standards (Target State)
✅ No duplicate implementations for the same behavior
✅ 100% test pass rate maintained before and after changes
✅ Zero warnings maintained (all warnings investigated and resolved)
✅ Clear git history with detailed commit messages
✅ Zero breaking changes to existing user-critical workflows
✅ TDD or immediate regression-test coverage for bug fixes and new logic
