#[cfg(any(test, target_os = "switch"))]
mod model;

#[cfg(target_os = "switch")]
mod runtime;
