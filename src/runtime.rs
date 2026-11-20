use crate::model::{self, Guard, Refusal, MAIN, TITLE};
use core::sync::atomic::{AtomicUsize, Ordering};
use skyline::hooks::{getRegionAddress, Region};
use skyline::{nn, patching::Patch};
use std::alloc::{GlobalAlloc, Layout, System};
use std::io::Write;

static HEAP_ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

struct CountingAllocator;

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        HEAP_ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) };
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

#[skyline::main(name = "ssbu-no-attract")]
pub fn main() {
    let (result, site) = install();
    let mut buffer = [0; 160];
    let mut cursor = buffer.as_mut_slice();
    if writeln!(
        cursor,
        "plugin=ssbu-no-attract/{} result={result} site={site} heap_allocations={}",
        env!("CARGO_PKG_VERSION"),
        HEAP_ALLOCATIONS.load(Ordering::Relaxed),
    )
    .is_ok()
    {
        let unused = cursor.len();
        let line = &buffer[..buffer.len() - unused];
        if let Ok(text) = core::str::from_utf8(line) {
            skyline::logging::log(text);
        }
        write_install_file(line);
    }
}

fn install() -> (&'static str, &'static str) {
    let mut version = nn::oe::DisplayVersion { name: [0; 16] };
    unsafe { nn::oe::GetDisplayVersion(&mut version) };
    let text = unsafe { getRegionAddress(Region::Text) }.cast::<u8>();
    let end = unsafe { getRegionAddress(Region::Rodata) } as usize;

    match model::check_install(&version.name, |guard| guard_matches(text, end, guard)) {
        Ok(()) => {}
        Err(Refusal::UnsupportedVersion) => return ("unsupported_version", "none"),
        Err(Refusal::GuardMismatch(name)) => return ("guard_mismatch", name),
    }
    if Patch::in_text(TITLE.offset).data(TITLE.branch).is_err() {
        return ("patch_failed", "title");
    }
    if Patch::in_text(MAIN.offset).data(MAIN.branch).is_err() {
        return match Patch::in_text(TITLE.offset).data(TITLE.stock) {
            Ok(()) => ("patch_failed", "main"),
            Err(_) => ("rollback_failed", "title"),
        };
    }
    ("installed", "title,main")
}

fn guard_matches(text: *const u8, end: usize, guard: &Guard) -> bool {
    if text.is_null() {
        return false;
    }
    let text_size = end.saturating_sub(text as usize);
    if guard.offset + guard.guard.len() > text_size {
        return false;
    }

    // All guard offsets are word-aligned offsets into Skyline's main text mapping.
    let bytes = unsafe { text.add(guard.offset).cast::<[u8; 64]>().read() };
    bytes == guard.guard
}

fn write_install_file(line: &[u8]) {
    use nn::fs;
    let path = c"sd:/ultimate/ssbu-no-attract/events.log".as_ptr().cast();
    unsafe {
        fs::CreateDirectory(c"sd:/ultimate".as_ptr().cast());
        fs::CreateDirectory(c"sd:/ultimate/ssbu-no-attract".as_ptr().cast());
        fs::CreateFile(path, 0);
        let mut file = fs::FileHandle { handle: 0 };
        let mode = fs::OpenMode_OpenMode_Write | fs::OpenMode_OpenMode_Append;
        if fs::OpenFile(&mut file, path, mode as i32) == 0 {
            if fs::SetFileSize(file, 0) == 0 {
                let flush = fs::WriteOption {
                    flags: fs::WriteOptionFlag_WriteOptionFlag_Flush as i32,
                };
                fs::WriteFile(file, 0, line.as_ptr(), line.len() as u64, &flush);
            }
            fs::CloseFile(file);
        }
    }
}
