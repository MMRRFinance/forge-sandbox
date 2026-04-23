# Pattern: 4-Tier Funding Account Waterfall

**Type:** Pattern (use this — but extract to a shared helper)  
**Category:** Business Logic / Account Selection  
**Status:** Canonical business logic — currently duplicated (see tech debt WorkItem `fb252e42`)

---

## Name

4-tier funding account waterfall — the ordered selection algorithm for choosing which bank account to use as the funding source for a loan or payment.

---

## File Paths

Where the pattern is implemented (currently duplicated):
- `self-service-api/src/index.ts:200–250` — first pass in `applyForReLoan` (with tier tracking)
- `self-service-api/src/index.ts:262–280` — retry pass in `applyForReLoan` (without tier tracking — diverged copy)

Where the pattern is referenced:
- `self-service-api/src/payments/textToPay.ts` — `processTextToPayPayment` uses a similar account selection
- `self-service-api/src/loanSetup/activate.ts:87` — `fundingAccountId` selection in loan activation
- `payments/src/payment_account_cleanup.ts:199` — `fundingAccount?.accountNumber?.endsWith(primaryLast4)` — uses primary account concept

Where it should live (not yet extracted):
- `self-service-api/src/utils/selectFundingAccount.ts` — **does not exist yet** — see tech debt WorkItem `fb252e42`

---

## How It Works

The waterfall selects a checking account from a customer's account list using a strict priority order. Each tier is tried in sequence; the first match wins.

```
Tier 1: Primary ACH account     (a.isPrimary === true)
Tier 2: Secondary ACH account   (a.isSecondary === true)
Tier 3: Previous loan's account (matched by routing + account number from last approval)
Tier 4: Any checking account    (checkingAccounts[0] — last resort)
```

If no account is found after all 4 tiers, the system runs `auditSingleCustomer()` to sync missing accounts from the payment provider, then retries the same 4-tier waterfall. If still no account, it throws.

### Current implementation (from `self-service-api/src/index.ts:200–278`)

```typescript
const accounts = await invokeLambda<ExternalAccount[]>(
  'getCustomerAccounts',
  { customerId: customer.id }
);
const checkingAccounts = (accounts ?? []).filter(
  (a) => a.type === 'Checking'
) as BankAccount[];

// Tier 1: Primary ACH
let fundingAccount: BankAccount | undefined = checkingAccounts.find(a => a.isPrimary);
let fundingAccountTier = 'primary';

// Tier 2: Secondary ACH
if (!fundingAccount) {
  fundingAccount = checkingAccounts.find(a => a.isSecondary);
  fundingAccountTier = 'secondary';
}

// Tier 3: Previous loan's funding account
if (!fundingAccount) {
  const previousApproval = customer.approvals
    ?.filter(a => a.fundingAccount)
    .sort((a, b) => new Date(b.approveDate).getTime() - new Date(a.approveDate).getTime())[0];
  if (previousApproval?.fundingAccount) {
    const prev = previousApproval.fundingAccount;
    fundingAccount = checkingAccounts.find(
      a => a.routingNumber === prev.routingNumber && a.accountNumber === prev.accountNumber
    );
    fundingAccountTier = 'previous';
  }
}

// Tier 4: Any checking account
if (!fundingAccount) {
  fundingAccount = checkingAccounts[0];
  fundingAccountTier = 'fallback';
}

// Observability: log which tier was selected
console.log('Funding account selection tier:', {
  customerId: customer.id,
  tier: fundingAccountTier,
});
```

### Retry path (after `auditSingleCustomer`)

If no account is found after the first pass, the system audits the customer and retries:

```typescript
await auditSingleCustomer(customer.id as string);
const retriedAccounts = await invokeLambda<ExternalAccount[]>(
  'getCustomerAccounts',
  { customerId: customer.id }
);
const retriedChecking = (retriedAccounts ?? []).filter(
  (a) => a.type === 'Checking'
) as BankAccount[];

// ⚠️ DIVERGED COPY — missing tier tracking, compressed syntax
fundingAccount =
  retriedChecking.find((a) => a.isPrimary) ??
  retriedChecking.find((a) => a.isSecondary) ??
  (() => {
    const previousApproval = customer.approvals
      ?.filter((a) => a.fundingAccount)
      .sort((a, b) => new Date(b.approveDate).getTime() - new Date(a.approveDate).getTime())[0];
    if (previousApproval?.fundingAccount) {
      const prev = previousApproval.fundingAccount;
      return retriedChecking.find(
        (a) => a.routingNumber === prev.routingNumber && a.accountNumber === prev.accountNumber
      );
    }
    return undefined;
  })() ??
  retriedChecking[0];

if (!fundingAccount) {
  throw `No funding account found for customer ${customer.id}`;
}
fundingAccountTier = 'post-audit-fallback';
```

---

## When to Use

**Use this waterfall when:**
- Selecting a bank account for loan origination (`applyForReLoan`).
- Selecting a bank account for payment processing (`textToPay`, `processPayment`).
- Any context where a customer may have multiple checking accounts and you need a deterministic selection.

**The tier order encodes business rules:**
- **Primary first** — the customer explicitly designated this account for ACH.
- **Secondary second** — the customer designated a backup.
- **Previous loan's account third** — if the customer has no designated account, use what worked last time (reduces payment failures from account changes).
- **Any checking last** — last resort; avoids blocking the customer entirely.

**Do NOT:**
- Skip tiers (e.g., go straight to Tier 4) — the tier order is a business requirement, not a performance optimization.
- Use savings accounts — the filter `a.type === 'Checking'` is intentional. Savings accounts have ACH restrictions.
- Implement this logic inline in a new location — extract to `selectFundingAccount()` helper first (see tech debt WorkItem `fb252e42`).

---

## Canonical Example

The reference implementation is `self-service-api/src/index.ts:200–250` (first pass, with tier tracking). The retry pass at lines 262–280 is a diverged copy that is missing tier tracking — do not use it as the reference.

### Proposed extracted helper (not yet implemented)

```typescript
// self-service-api/src/utils/selectFundingAccount.ts (PROPOSED — see WorkItem fb252e42)

export interface FundingAccountSelection {
  account: BankAccount | undefined;
  tier: 'primary' | 'secondary' | 'previous' | 'fallback' | 'not-found';
}

export function selectFundingAccount(
  checkingAccounts: BankAccount[],
  previousApprovals?: CustomerApproval[]
): FundingAccountSelection {
  // Tier 1: Primary ACH
  const primary = checkingAccounts.find(a => a.isPrimary);
  if (primary) return { account: primary, tier: 'primary' };

  // Tier 2: Secondary ACH
  const secondary = checkingAccounts.find(a => a.isSecondary);
  if (secondary) return { account: secondary, tier: 'secondary' };

  // Tier 3: Previous loan's funding account
  const lastApproval = previousApprovals
    ?.filter(a => a.fundingAccount)
    .sort((a, b) => new Date(b.approveDate).getTime() - new Date(a.approveDate).getTime())[0];
  if (lastApproval?.fundingAccount) {
    const prev = lastApproval.fundingAccount;
    const matched = checkingAccounts.find(
      a => a.routingNumber === prev.routingNumber && a.accountNumber === prev.accountNumber
    );
    if (matched) return { account: matched, tier: 'previous' };
  }

  // Tier 4: Any checking account
  if (checkingAccounts[0]) return { account: checkingAccounts[0], tier: 'fallback' };

  return { account: undefined, tier: 'not-found' };
}
```

---

## Gotchas

1. **The retry path is a diverged copy.** `self-service-api/src/index.ts:262–280` implements the same waterfall but without `fundingAccountTier` tracking. If you change the waterfall logic, you must update both copies until the extraction is done. See tech debt WorkItem `fb252e42`.

2. **`throw \`string\`` in the no-account path.** Line 278 throws a template literal string, not an `Error` object. This loses the stack trace. See tech debt WorkItem `cdf7f355`.

3. **The audit retry is expensive.** `auditSingleCustomer()` makes external API calls to sync accounts. It should only run when all 4 tiers fail — not as a first resort. The current implementation is correct on this point.

4. **Tier 3 matches by routing + account number.** This is intentional — the `isPrimary`/`isSecondary` flags may not be set on the account object returned from the payment provider after an audit. Matching by routing + account number is the fallback identity check.

5. **`textToPay` has a similar but not identical waterfall.** `self-service-api/src/payments/textToPay.ts` selects accounts for payment processing. It may have different tier logic (e.g., it may prefer the account used for the specific loan being paid). Do not assume the reloans waterfall applies to payments without checking.

---

## Related Patterns

- [`captureError-rethrow.md`](./captureError-rethrow.md) — the error monitoring pattern that should wrap the `throw` at the end of this waterfall
- Tech debt WorkItem `fb252e42` — extract `selectFundingAccount()` helper to eliminate the duplicated retry path
- Tech debt WorkItem `cdf7f355` — fix `throw \`string\`` to `throw new Error(...)` at line 278
