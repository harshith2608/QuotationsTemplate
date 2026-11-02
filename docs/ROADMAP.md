# Roadmap: ideas on hold

Ideas agreed as worth doing but not started. Each has what it is, how it would work, what it costs and what to check
first. Move an idea out of here when work starts.

## Laser measure straight into the quotation (research)

*Proposed 25 Oct 2026. Research only.*

**The idea.** Designers measure rooms with a laser distance meter. Instead of reading the screen and typing, the
reading goes straight into the size box on the quotation: tap Length, press measure, done. A strong marketing line too.

**What we found (Bosch GLM 50-27 CG, ₹10,499 on Bosch India).** 50 m range, ±1.5 mm, metres or ft/in, Bluetooth Low
Energy, but only for Bosch's own MeasureOn app: no "keyboard mode" (HID) that would type readings into any app, and
Bosch doesn't publish its Bluetooth protocol (hobbyists have decoded the older GLM 50 C / 100 C; the 50-27 CG may be
similar, untested).

**Three kinds of meter, three ways in.**
1. **Keyboard mode (HID)** meters (some Leica DISTO, Hilti and other models): they type into the selected box already,
   no change to the app. Only gap: our size boxes are feet + inches, meters send decimals.
2. **Bluetooth, brand app only** (Bosch GLM, most others): a "Connect laser" button using Web Bluetooth. Works in Chrome
   on Android and laptops, **not on iPhone/iPad** (Safari has no Web Bluetooth). Per brand, unofficial for Bosch (a
   firmware update could break it); Leica's protocol is better documented.
3. **USB only**: not practical on site.

**Cheap first step (any meter).** Let size boxes accept a decimal in metres or feet (2.438 m → 8 ft 0 in), so a reading
copied from any meter or its app is quick to enter.

**Before starting.**
- Ask customers whether they own a laser meter, and which brand/model.
- Buy the most common one and test: keyboard mode, or decode its Bluetooth messages with a BLE scanner (nRF Connect).
- Decide whether Android-only is acceptable (check how many customers quote on iPhone).
