# No Attract

No Attract keeps Super Smash Bros. Ultimate on the title screen or main menu when you leave it idle.

<video src="https://git.syntaxbyexample.com/intpa/ssbu-no-attract/media/blob/88bc3a299a08a4547b97d2ee00eeb6598e06d299" aria-label="Watch the stock and No Attract comparison" autoplay muted loop playsinline controls></video> [Open the clip](docs/media/no-attract-preview.mp4)

*Stock enters How to Play after 4:16 idle on Main. With No Attract, Main is still open at 9:10. Recorded in Eden on 2026-11-20 with the v0.1.0 NRO.* [Watch the MP4](https://git.syntaxbyexample.com/intpa/ssbu-no-attract/src/branch/main/docs/media/no-attract.mp4)

## Install

No Attract v0.1.0 (2026-11-20) keeps idle players on the title screen or main menu.

### What you need

| Thing | Upstream | Our fork | What the fork changes |
| --- | --- | --- | --- |
| Switch firmware | [latest](https://en-americas-support.nintendo.com/app/answers/detail/a_id/22525) | — | — |
| Super Smash Bros. Ultimate | 13.0.5 | — | — |
| Atmosphère | [latest](https://github.com/Atmosphere-NX/Atmosphere/releases/latest) | [RO cleanup](https://git.syntaxbyexample.com/intpa/atmosphere-ro-cleanup-p1) | Cleans up after a module fails to load. |
| Skyline | [latest](https://github.com/skyline-dev/skyline/releases/latest) | [Skyline fork](https://git.syntaxbyexample.com/intpa/skyline) | Protects the logging queue when multiple threads write. |

### Install

1. Fully close Smash. Download `libssbu_no_attract.nro` from [release v0.1.0](https://git.syntaxbyexample.com/intpa/ssbu-no-attract/releases/tag/v0.1.0).
2. Copy it to `sd:/atmosphere/contents/01006A800016E000/romfs/skyline/plugins/libssbu_no_attract.nro` on the SD card. Replace the existing file if prompted.
3. Start Smash.

Keep `manifest.json` and `SHA256SUMS.txt` on your computer for checking the download.

**Update:** Close Smash and replace the same NRO.

**Uninstall:** Close Smash, delete the NRO from the path above and restart the game.

### What changed

| Feature | Change |
| --- | --- |
| Title screen | Leave the title screen idle without starting How to Play. |
| Main menu | Leave the main menu idle without returning to the title screen. |

[Read the No Attract guide](https://git.syntaxbyexample.com/intpa/ssbu-no-attract/src/tag/v0.1.0/README.md).

### Tested on

| Feature | Hardware | Eden |
| --- | --- | --- |
| Idle title screen | No | Yes |
| Idle main menu | No | Yes |

### Known limits

- Applies only to the title screen and main menu in Smash 13.0.5.

## Build

```text
cargo test
cargo skyline build --release
```

This project was developed with the assistance of AI.

## License

MIT. See [LICENSE](LICENSE).
