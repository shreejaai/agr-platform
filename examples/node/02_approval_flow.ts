/**
 * AGR Approval Flow — full lifecycle in TypeScript.
 * Evaluates a large transfer, auto-approves after 3s, then waits for the decision.
 */
import { AGRClient } from '../../packages/agr-sdk-ts/src/index.js'

const API_KEY = process.env['AGR_API_KEY'] || 'agr_sk_YOUR_KEY_HERE'
const BASE_URL = process.env['AGR_BASE_URL'] || 'http://localhost:8000'

const agr = new AGRClient({ apiKey: API_KEY, baseUrl: BASE_URL })

async function autoApprove(approvalId: string, delayMs = 3000): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, delayMs))
  console.log(`\n  [auto-approver] Approving ${approvalId}...`)
  const resp = await fetch(`${BASE_URL}/v1/approvals/${approvalId}/approve`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ comment: 'Auto-approved by Node.js example' }),
  })
  if (!resp.ok) {
    console.error(`  [auto-approver] HTTP ${resp.status}`)
  } else {
    console.log(`  [auto-approver] Done`)
  }
}

async function main(): Promise<void> {
  console.log('=== AGR Approval Flow Demo (TypeScript) ===\n')

  // Step 1: Evaluate
  console.log('--- Step 1: Evaluate transfer_funds ($50,000) ---')
  const result = await agr.evaluate(
    'finance-agent',
    'transfer_funds',
    'bank-account-001',
    { amount: 50000, destination_country: 'IN' },
  )

  console.log(`  Decision:    ${result.decision}`)
  console.log(`  Approval ID: ${result.approvalId ?? 'N/A'}`)
  console.log(`  Risk Score:  ${result.riskScore}`)

  if (!result.requiresApproval) {
    console.log(`\n  ⚠️  Expected APPROVAL_REQUIRED, got ${result.decision}`)
    console.log('  Import finance_controls policies first:')
    console.log('    bash ../curl/08_import_policies_yaml.sh --commit')
    return
  }

  console.log('\n✅ APPROVAL_REQUIRED — auto-approving in 3 seconds...')

  // Step 2: Start auto-approver in background
  console.log('\n--- Step 2: Starting auto-approver ---')
  const approvalPromise = autoApprove(result.approvalId!)

  // Step 3: Wait for approval
  console.log('\n--- Step 3: Polling for approval decision ---')
  const approved = await agr.waitForApproval(result.approvalId!, {
    pollInterval: 1000,
    timeout: 30000,
  })
  await approvalPromise

  if (approved) {
    console.log('\n✅ Transfer approved — agent may now execute')
  } else {
    console.log('\n❌ Transfer rejected or timed out')
  }

  // Step 4: Show audit events
  console.log('\n--- Step 4: Recent audit events ---')
  const auditResp = await fetch(`${BASE_URL}/v1/audit?limit=5`, {
    headers: { Authorization: `Bearer ${API_KEY}` },
  })
  if (auditResp.ok) {
    const audit = await auditResp.json() as { items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>
    const items = Array.isArray(audit) ? audit : (audit.items ?? [])
    for (const event of items.slice(0, 5)) {
      const type = String(event['event_type'] ?? '?').padEnd(25)
      console.log(`  [${type}] agent=${event['agent_id']} action=${event['action']}`)
    }
  }

  console.log('\n✅ Approval lifecycle complete')
}

main().catch(console.error)
