const SUPPORTED_VERSION: &[u8] = b"13.0.5";

pub struct Guard {
    pub name: &'static str,
    pub offset: usize,
    pub guard: [u8; 64],
}

pub struct Patch {
    pub offset: usize,
    pub stock: u32,
    pub branch: u32,
}

pub const TITLE: Patch = Patch {
    offset: 0x1bfb108,
    stock: 0x54000c0a,
    branch: 0x14000060,
};
pub const MAIN: Patch = Patch {
    offset: 0x185e53c,
    stock: 0x5400012d,
    branch: 0x14000009,
};

// Stock 13.0.5 main text, build ID 21450c647b8c5940ed5b68218ea128fd3c5d597d.
const GUARDS: [Guard; 4] = [
    Guard {
        name: "title_compare",
        offset: 0x1bfb0e8,
        guard: [
            0x48, 0x02, 0x00, 0x34, 0x69, 0x76, 0x40, 0xf9, 0x29, 0x01, 0x40, 0xf9, 0x29, 0x01,
            0x40, 0xf9, 0x29, 0x01, 0x43, 0xf9, 0x68, 0x0a, 0x41, 0xb9, 0x29, 0x99, 0x44, 0xb9,
            0x1f, 0x01, 0x09, 0x6b, 0x0a, 0x0c, 0x00, 0x54, 0xe8, 0x03, 0x00, 0x32, 0x68, 0x32,
            0x04, 0x39, 0x68, 0xd6, 0x80, 0xb9, 0x1f, 0x4d, 0x00, 0x71, 0x22, 0x0c, 0x00, 0x54,
            0x68, 0x0a, 0x08, 0x8b, 0xe9, 0x03, 0x1e, 0x32,
        ],
    },
    Guard {
        name: "title_resume",
        offset: 0x1bfb280,
        guard: [
            0xff, 0x0b, 0x00, 0xf9, 0xff, 0x83, 0x00, 0x39, 0xfd, 0x7b, 0x49, 0xa9, 0xf7, 0x33,
            0x40, 0xf9, 0xf4, 0x4f, 0x48, 0xa9, 0xf6, 0x57, 0x47, 0xa9, 0xff, 0x83, 0x02, 0x91,
            0xc0, 0x03, 0x5f, 0xd6, 0xec, 0x1c, 0x77, 0x94, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xe8, 0x0f, 0x1d, 0xfc, 0xf4, 0x4f, 0x01, 0xa9,
            0xfd, 0x7b, 0x02, 0xa9, 0xfd, 0x83, 0x00, 0x91,
        ],
    },
    Guard {
        name: "main_compare",
        offset: 0x185e524,
        guard: [
            0xe8, 0x03, 0x1f, 0x2a, 0xc8, 0x01, 0x00, 0x37, 0x68, 0x76, 0x40, 0xf9, 0x08, 0x99,
            0x44, 0xb9, 0x69, 0xf2, 0x40, 0xb9, 0x1f, 0x01, 0x09, 0x6b, 0x2d, 0x01, 0x00, 0x54,
            0xe8, 0x06, 0x02, 0xb0, 0x08, 0xc5, 0x44, 0xf9, 0x08, 0x05, 0x40, 0xf9, 0x09, 0x01,
            0x40, 0xb9, 0x29, 0x01, 0x13, 0x32, 0x09, 0x01, 0x00, 0xb9, 0xe8, 0x03, 0x1f, 0x32,
            0x68, 0xca, 0x00, 0xb9, 0x68, 0x6e, 0x40, 0xf9,
        ],
    },
    Guard {
        name: "main_resume",
        offset: 0x185e560,
        guard: [
            0x68, 0x6e, 0x40, 0xf9, 0x08, 0x41, 0x40, 0xf9, 0x08, 0x21, 0x40, 0xf9, 0x08, 0x01,
            0x40, 0xf9, 0xa8, 0x00, 0x00, 0xb4, 0x08, 0x05, 0x40, 0xf9, 0x68, 0x00, 0x00, 0xb4,
            0x75, 0x22, 0x03, 0x91, 0x41, 0x00, 0x00, 0x14, 0xb4, 0xd5, 0x01, 0xd0, 0x94, 0x62,
            0x13, 0x91, 0x88, 0xfe, 0xdf, 0x08, 0x28, 0x09, 0x00, 0x36, 0x60, 0x6e, 0x40, 0xf9,
            0x08, 0x00, 0x40, 0xf9, 0x08, 0x11, 0x40, 0xf9,
        ],
    },
];

#[derive(Debug, PartialEq, Eq)]
pub enum Refusal {
    UnsupportedVersion,
    GuardMismatch(&'static str),
}

/// Check all text before allowing the caller to write either instruction.
pub fn check_install(
    version: &[u8],
    mut matches: impl FnMut(&Guard) -> bool,
) -> Result<(), Refusal> {
    let end = version
        .iter()
        .position(|&byte| byte == 0)
        .unwrap_or(version.len());
    if &version[..end] != SUPPORTED_VERSION {
        return Err(Refusal::UnsupportedVersion);
    }
    for guard in &GUARDS {
        if !matches(guard) {
            return Err(Refusal::GuardMismatch(guard.name));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn patches_follow_each_stock_non_expiry_edge() {
        for (patch, guard, target) in [
            (TITLE, &GUARDS[0], 0x1bfb288),
            (MAIN, &GUARDS[2], 0x185e560),
        ] {
            let byte_offset = patch.offset - guard.offset;
            let stock_word = u32::from_le_bytes(
                guard.guard[byte_offset..byte_offset + 4]
                    .try_into()
                    .unwrap(),
            );
            assert_eq!(patch.stock, stock_word);
            assert_eq!(patch.stock & 0xff00_0010, 0x5400_0000);
            let stock_destination = patch.offset + ((patch.stock >> 5) & 0x7ffff) as usize * 4;
            assert_eq!(stock_destination, target);
            assert_eq!(patch.branch & 0xfc00_0000, 0x1400_0000);
            let destination = patch.offset + (patch.branch & 0x03ff_ffff) as usize * 4;
            assert_eq!(destination, target);
        }
    }

    #[test]
    fn manual_title_route_bypasses_idle_branch() {
        let guard = &GUARDS[0];
        let manual_branch = u32::from_le_bytes(guard.guard[..4].try_into().unwrap());
        assert_eq!(manual_branch & 0xff00_001f, 0x3400_0008);
        let target = guard.offset + ((manual_branch >> 5) & 0x7ffff) as usize * 4;
        assert_eq!(target, 0x1bfb130);
        assert!(guard.offset < TITLE.offset && TITLE.offset < target);
    }

    #[test]
    fn installation_requires_every_guard() {
        assert_eq!(check_install(b"13.0.5\0", |_| true), Ok(()));
        for changed in &GUARDS {
            assert_eq!(
                check_install(b"13.0.5", |guard| {
                    assert_eq!(guard.guard.len(), 64);
                    guard.offset != changed.offset
                }),
                Err(Refusal::GuardMismatch(changed.name))
            );
        }
        for version in [b"13.0.3".as_slice(), b"13.0.50", b""] {
            assert_eq!(
                check_install(version, |_| panic!("unexpected text read")),
                Err(Refusal::UnsupportedVersion)
            );
        }
    }

    #[test]
    fn package_is_standalone_and_mit_licensed() {
        let manifest = include_str!("../Cargo.toml");
        assert!(manifest.contains("license = \"MIT\""));
        assert!(manifest.contains("crate-type = [\"cdylib\"]"));
        assert!(!manifest.contains("[workspace]"));
        let license = include_str!("../LICENSE");
        assert!(license.contains("Copyright (c) 2026 intpa"));
        assert!(license.contains("Permission is hereby granted, free of charge"));
    }
}
