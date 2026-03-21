/**
 * AGR Policy Import — bulk import via /v1/policies/import.
 * Dry-run first, then confirm import.
 */

const API_KEY = process.env['AGR_API_KEY'] || 'agr_sk_YOUR_KEY_HERE'
const BASE_URL = process.env['AGR_BASE_URL'] || 'http://localhost:8000'

interface PolicyImportItem {
  name: string
  level: string
  cedar_rule: string
  active: boolean
}

interface ImportPayload {
  policies: PolicyImportItem[]
  dry_run: boolean
  overwrite: boolean
}

const POLICIES: PolicyImportItem[] = [
  {
    name: 'require-approval-large-transfer',
    level: 'org',
    cedar_rule:
      'forbid(principal, action == Action::"transfer_funds", resource) ' +
      'when { context has amount && context.amount > 25000 } ' +
      'unless { context has approval_status && context.approval_status == "approved" };',
    active: true,
  },
  {
    name: 'deny-international-transfer',
    level: 'org',
    cedar_rule:
      'forbid(principal, action == Action::"transfer_funds", resource) ' +
      'when { context has destination_country && context.destination_country != "IN" };',
    active: true,
  },
  {
    name: 'allow-small-internal-transfer',
    level: 'org',
    cedar_rule:
      'permit(principal, action == Action::"transfer_funds", resource) ' +
      'when { context has amount && context.amount <= 5000 };',
    active: true,
  },
  {
    name: 'deny-deploy-prod-by-default',
    level: 'org',
    cedar_rule:
      'forbid(principal, action == Action::"deploy", resource) ' +
      'when { context has environment && context.environment == "production" };',
    active: true,
  },
  {
    name: 'allow-read-ticket-status',
    level: 'org',
    cedar_rule: 'permit(principal, action == Action::"read_ticket_status", resource);',
    active: true,
  },
]

async function importPolicies(dryRun: boolean): Promise<Record<string, unknown>> {
  const payload: ImportPayload = {
    policies: POLICIES,
    dry_run: dryRun,
    overwrite: false,
  }

  const resp = await fetch(`${BASE_URL}/v1/policies/import`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`HTTP ${resp.status}: ${text}`)
  }

  return resp.json() as Promise<Record<string, unknown>>
}

async function main(): Promise<void> {
  console.log('=== AGR Policy Import (TypeScript) ===\n')

  // Step 1: Dry run
  console.log('--- Step 1: Dry-run preview ---')
  const dryResult = await importPolicies(true)
  console.log('  Dry-run result:', JSON.stringify(dryResult, null, 2))
  console.log()

  // Step 2: Real import
  console.log('--- Step 2: Importing for real ---')
  const realResult = await importPolicies(false)
  console.log('  Import result:', JSON.stringify(realResult, null, 2))
  console.log()

  console.log(`✅ ${POLICIES.length} policies imported`)
}

main().catch(console.error)
