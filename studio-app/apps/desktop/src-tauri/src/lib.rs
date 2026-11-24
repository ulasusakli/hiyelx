//! Strictly confined local workspace filesystem IPC for HIYELX Studio.
//!
//! Architectural invariant (ADR 0002 v1.1):
//! - Tauri manages only desktop UI lifecycle and workspace-confined files.
//! - Tauri never accesses USB, serial, CAN, GPIO, or executes Runtime drivers.

use std::fs::{self, File};
use std::io::Write;
use std::path::{Component, Path, PathBuf};

/// Resolves `relative_path` strictly inside `workspace_root` without allowing
/// parent traversal, absolute paths, or symlink escapes.
pub fn resolve_confined_path(workspace_root: &Path, relative_path: &str) -> Result<PathBuf, String> {
    if relative_path.trim().is_empty() {
        return Err("workspace path must not be blank".to_string());
    }
    if relative_path.contains('\\') || relative_path.starts_with('/') {
        return Err("workspace path must be a relative POSIX path".to_string());
    }

    let root = fs::canonicalize(workspace_root)
        .map_err(|_| "workspace root could not be resolved".to_string())?;
    let mut current = root.clone();

    for component in Path::new(relative_path).components() {
        match component {
            Component::Normal(segment) => {
                current.push(segment);
                if let Ok(meta) = fs::symlink_metadata(&current) {
                    if meta.file_type().is_symlink() {
                        return Err("symlink components are forbidden inside workspace".to_string());
                    }
                }
            }
            _ => return Err("forbidden path traversal segment".to_string()),
        }
    }

    if !current.starts_with(&root) {
        return Err("resolved path escapes workspace root".to_string());
    }
    Ok(current)
}

/// Atomically writes UTF-8 content inside `workspace_root` via sibling temp file + fsync + rename.
pub fn write_file_atomic(
    workspace_root: &Path,
    relative_path: &str,
    content: &str,
) -> Result<(), String> {
    let target = resolve_confined_path(workspace_root, relative_path)?;
    let parent = target
        .parent()
        .ok_or_else(|| "target path has no parent directory".to_string())?;
    fs::create_dir_all(parent).map_err(|_| "failed to create parent directory".to_string())?;

    let file_name = target
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or_else(|| "invalid target filename".to_string())?;
    let tmp_path = parent.join(format!(".{file_name}.{}.tmp", std::process::id()));

    let write_result = (|| -> std::io::Result<()> {
        let mut handle = File::create(&tmp_path)?;
        handle.write_all(content.as_bytes())?;
        handle.sync_all()?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&tmp_path);
        return Err("failed to write temporary workspace file".to_string());
    }

    if fs::rename(&tmp_path, &target).is_err() {
        let _ = fs::remove_file(&tmp_path);
        return Err("failed to commit atomic workspace file replacement".to_string());
    }
    Ok(())
}

#[tauri::command]
fn workspace_read_file(workspace_root: String, relative_path: String) -> Result<String, String> {
    let target = resolve_confined_path(Path::new(&workspace_root), &relative_path)?;
    fs::read_to_string(target).map_err(|_| "failed to read workspace file".to_string())
}

#[tauri::command]
fn workspace_write_file_atomic(
    workspace_root: String,
    relative_path: String,
    content: String,
) -> Result<(), String> {
    write_file_atomic(Path::new(&workspace_root), &relative_path, &content)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            workspace_read_file,
            workspace_write_file_atomic
        ])
        .run(tauri::generate_context!())
        .expect("error while running HIYELX Studio desktop shell");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_traversal_and_absolute_paths() {
        let root = std::env::temp_dir().join("hiyelx-tauri-test-root");
        let _ = fs::create_dir_all(&root);
        assert!(resolve_confined_path(&root, "../escape.yaml").is_err());
        assert!(resolve_confined_path(&root, "/etc/passwd").is_err());
        assert!(resolve_confined_path(&root, "robot/robot.yaml").is_ok());
        let _ = fs::remove_dir_all(&root);
    }
}
