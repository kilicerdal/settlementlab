# Showcase walkthrough

## A two-minute narrative

A fictional broker submits 10,000 NOVA shares at $42.75. Manager allocations total 9,900 shares. The workbench surfaces the mismatch instead of advancing the trade. Correct the allocation, affirm the synthetic instruction, and attempt settlement. Insufficient inventory produces a failed attempt with evidence. Provision the synthetic balances, retry successfully, and reconcile a matching statement. The audit timeline preserves both failure and recovery.

## Evidence to publish

Use the automated browser journey to capture the actual interface and trace. Include the architecture diagram and CI result in a website case study. Explain the duplicate and concurrent-settlement tests alongside the screenshots: attractive UI alone does not establish correctness. Report measured run results with their environment; do not invent throughput, reliability, or coverage percentages.

The demo button creates real local records. The reconciliation button explicitly uses a generated matching statement; use the API to demonstrate missing and mismatched statement records. All counterparties, securities, balances, and instructions are fictional.

## Publishing boundaries

The source and recorded screenshots are suitable showcase materials. The unauthenticated loopback server is not a public website backend. Before interactive hosting, add identity, participant isolation, rate and resource limits, controlled resets, and deployment-specific security review. A static website case study can link to the repository and recorded demonstration immediately.
