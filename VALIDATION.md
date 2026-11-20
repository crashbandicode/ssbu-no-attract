# SSBU 13.0.5 validation

2026-11-20. The release candidate was built from `08f6547e0a508d03a0e7cec9a181adad53568370`. The 32,768-byte NRO has SHA-256 `f9cf7da18998e2d522876a7b77ddbe44739d128bae6246b92c2d20234297c1ab`.

The two patched AArch64 instructions use their original non-expiry destinations. Title at `main+0x1bfb108` branches to `main+0x1bfb288`. Main at `main+0x185e53c` branches to `main+0x185e560`. The Title Start decision bypasses the timeout branch, and Main's normal Lua processing resumes at the destination. The plugin validates four surrounding 64-byte windows before writing either branch. All four matched the stock 13.0.5 NSO in a separate byte comparison.

The missing-guard regression failed with one intentionally omitted window. The full guard set passed all four host tests. Strict all-target Clippy, the no-default-features build, the Skyline release build, and the separate empty-diag-feature build passed. The dated November 18 card copy contained 21 NROs. Their pinned hashes matched, and the offset scan found zero references near the sites or their guard windows.

The stock control on Yoga, `no-attract-stock-yoga-01a1f9cd-c`, used Eden `d34ddcc9b733` and the stock 13.0.5 main image. The active Title timer expired after 12.095 seconds (726 VI frames) and the bridge confirmed How to Play at 12.586 seconds. Main expired after 240.019 seconds (14,401 VI frames), returned to Title, then reached How to Play at 252.972 seconds. The raw trace, CRC-checked `ssbu.ui` state, and row receipts are in the companion workspace listed in [HANDOFF.md](HANDOFF.md).

The exact candidate completed all ten rows in one XPS boot, `no-attract-candidate-xps-01a1f9cd-b`, guest 81 and bridge boot `0xbbeec7a3ca2bd207`. XPS reused the Yoga stock receipts with matching Eden, game and observer plugin hashes. It exceeded twice the stock time to How to Play and twice the stock VI count on each menu.

| Menu | Stock How to Play | Exact candidate, still on menu |
| --- | ---: | ---: |
| Title | 12.586 seconds, 746 VI | 26.437 seconds, 1,587 VI |
| Main | 252.972 seconds, 15,165 VI | 535.531 seconds, 32,132 VI |

The timer counters crossed 720 and 14,400 on the candidate without either native expiry branch running. The same guest entered native Training, used Pause and Quit, and returned through fighter and stage select to native Main. The bridge verified scene and mode throughout. The final trace recorded zero timer expiry, How to Play, demo, unmapped accesses or file loss. Earlier partial boots are preserved separately in the companion handoff.
