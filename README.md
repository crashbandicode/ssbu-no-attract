# No Attract

No Attract keeps Super Smash Bros. Ultimate on the title screen or main menu when you leave it idle.

<video src="docs/media/no-attract.mp4" autoplay muted loop playsinline controls></video>

*Stock enters How to Play after 4:16 idle on Main. With No Attract, Main is still open at 9:10. Recorded in Eden on 2026-11-20 with the v0.1.0 NRO.* [Watch the MP4](https://git.syntaxbyexample.com/intpa/ssbu-no-attract/src/branch/main/docs/media/no-attract.mp4)

## Install

Requires Super Smash Bros. Ultimate 13.0.5 and Skyline. Copy `libssbu_no_attract.nro` to `atmosphere/contents/01006A800016E000/romfs/skyline/plugins/` on your SD card. [Download the NRO](https://git.syntaxbyexample.com/intpa/ssbu-no-attract/releases/tag/v0.1.0)

## Build

```text
cargo test
cargo skyline build --release
```

This project was developed with the assistance of AI.

## License

MIT. See [LICENSE](LICENSE).
