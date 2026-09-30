# soundcore P31i owner test

- Owner: [@mikesmenzvdsa](https://github.com/mikesmenzvdsa)
- Device: soundcore P31i, `34:09:C9:A4:68:10`
- Revision tested: working tree before the contribution commit, with the
  dedicated `d1202` model row
- Initial mode: Off, read from `06 01`
- Initial battery: left 100%, right 100%, case 20%, from Fast Pair

The Soundcore probe and shell bridge both reached device-reported Off, ANC and
Ambient. The device acknowledged each write and returned the resulting `06 01`
mode notification. The final Off setting was read back from the device and
restored. No guessed bytes were used; the complete raw session is in
`docs/captures/soundcore-p31i.txt`.

Not tested or not applicable in this owner session: charging transitions,
case-open/closed changes, disconnect/reconnect recovery, isolation from a
second connected headphone set, and acoustic noise-cancellation quality.
Ambient-level and wind-noise controls were not confirmed for the P31i.
