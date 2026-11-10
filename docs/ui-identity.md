# Console UI identity

The console should feel like a **lab instrument**: something an engineer uses to measure sandboxes, not a marketing dashboard. Any change to `web/` keeps to these rules.

## The five commitments

1. **Neutrals: true black and pure grays.** No blue or warm tint. Dark: `#000` page, `#0A0A0A` panels, `#282828` lines, `#ECECEC` text, `#8C8C8C` secondary text. Light mirrors this on `#FAFAFA` and white.
2. **Corners: square.** Every radius token is `0`, set once in `tailwind.config.ts`. Do not add rounded corners back per component.
3. **Type: IBM Plex Sans for the interface, IBM Plex Mono for code, ids and output.** Ligatures are off for anything monospaced: code must read exactly as typed.
4. **One accent: signal orange `#FF7A1A`, meaning "happening right now".** It is used for the phase in progress, the live cursor, the live-sandbox indicator, the logo and the primary Run buttons. Nothing finished is orange.
5. **Signature: square indicator lights.** Every status marker is a small square, like an LED on a panel. Never a circle, never a coloured stripe.

## Colour carries meaning, so it is never decoration

| Colour | Means | Token |
| --- | --- | --- |
| Green `#3ECF8E` | The run succeeded | `ok` |
| Yellow `#F2C94C` | Your code failed (the sandbox worked) | `user` |
| Blue `#67B7FF` | Timed out | `late` |
| Red `#FF5555` | The platform failed, not your code | `infra` |
| Orange `#FF7A1A` | Live right now | `live` |

Syntax highlighting does not use these colours. Keywords are structured by weight; strings and numbers use the dedicated `code-str` and `code-num` tokens.

## Avoid

- Glows, gradients, glass effects and drop shadows.
- Coloured left-border strips on selected or highlighted items.
- Text buttons for icon actions (history, theme, source). Use icons with an `aria-label` and a tooltip.
- New fonts, a second accent colour, or violet anywhere.

## Voice

Plain sentences that say what happened and whose fault it was ("Your code failed. The sandbox worked fine."). No hype words, no em dashes in interface copy.
