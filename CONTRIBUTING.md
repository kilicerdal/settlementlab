# Contributing

Use Python 3.9 or later. Keep all trades, accounts, instructions, and balances synthetic.

1. Create a focused branch.
2. Make the smallest coherent change; document changes to lifecycle rules and API contracts.
3. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
4. If the interface changes, run the browser journey described in the README and inspect both screenshots.
5. Include the reason for the change, observed behavior, and verification in the pull request.

For financial and state-transition changes, add a test with independently calculated expected values. Cover invalid transitions and transaction rollback. Preserve exact integer-cent settlement arithmetic and request/version guards. Do not add external financial-service integrations or real participant data to demonstration fixtures.

Keep future features distinct from implemented capabilities. Public-facing claims must correspond to reproducible tests or recorded evidence.
