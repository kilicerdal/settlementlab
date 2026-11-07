# Local demonstration security boundary

SettlementLab V2.2 binds to loopback and uses fictional data. Shared-ledger writes require server-resolved demo roles; opaque expiring cookies are HttpOnly and SameSite=Strict. Request-body role/actor fields do not grant authority. Makers cannot approve their own instruction requests; checkers authorize settlement and reserve funding; auditors cannot perform shared writes.

Anyone using this local demo can freely select a persona. This is not proof of human identity, production authentication, or participant data isolation. Synthetic reads are public locally. Legacy trade-scoped endpoints retain their pre-governance contract and cannot mutate shared balances or bypass shared trade approval. Do not expose this server as a public financial API.

Journal and approval data are transactional but not tamper-proof. Integrity checks detect projection and balancing breaks; they do not replace access controls or independent custody/accounting reconciliation. No real money moves. Local AI can suggest investigation but has no mutation tools.

Never include real financial records or credentials in fixtures, issues, screenshots or traces. Use private vulnerability reporting if available for security-sensitive details. Public hosting requires verified identity, participant authorization, hardened sessions/CSRF/transport, resource controls and deployment-specific review.
