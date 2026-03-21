import { AGRClient } from '../../packages/agr-sdk-ts/src/index.js'

const agr = new AGRClient({
  apiKey: process.env['AGR_API_KEY'] || 'agr_sk_YOUR_KEY_HERE',
  baseUrl: process.env['AGR_BASE_URL'] || 'http://localhost:8000',
})

async function main() {
  const result = await agr.evaluate('ts-agent', 'read_ticket_status', 'ticket-42', {
    department: 'engineering',
  })

  console.log(`Decision:   ${result.decision}`)
  console.log(`Risk Score: ${result.riskScore}`)
  console.log(`Allowed:    ${result.allowed}`)

  if (result.allowed) {
    console.log('✅ Agent may execute')
  } else if (result.requiresApproval) {
    console.log(`⏳ Approval required: ${result.approvalId}`)
    const approved = await agr.waitForApproval(result.approvalId!, {
      pollInterval: 2000,
      timeout: 60000,
    })
    console.log(approved ? '✅ Approved' : '❌ Rejected or timed out')
  } else {
    console.log(`🚫 Denied: ${result.reason}`)
  }
}

main().catch(console.error)
