fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "save_markdown_export",
            "pick_local_ai_import_directory",
            "reveal_managed_path",
            "native_notification_permission_state",
            "request_native_notification_permission",
            "deliver_round_notification",
            "update_generation_sleep_inhibition",
        ]),
    ))
    .expect("failed to build the AQA desktop shell")
}
