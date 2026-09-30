"""Native desktop window lifecycle contracts."""

from pathlib import Path


def test_macos_close_hides_the_application_and_dock_reopen_reveals_it() -> None:
    source = (Path(__file__).parents[1] / "desktop/src-tauri/src/main.rs").read_text()

    window_events = source.split(".on_window_event", 1)[1]
    macos_close = window_events.split('#[cfg(target_os = "macos")]', 1)[1]
    macos_close = macos_close.split('#[cfg(not(target_os = "macos"))]', 1)[0]
    assert "api.prevent_close();" in macos_close
    assert "window.app_handle().hide()" in macos_close
    assert "RunEvent::Reopen" in source
    assert "} => reveal_main_window(app)" in source
    assert "fn reveal_main_window(app: &AppHandle)" in source
    reveal = source.split("fn reveal_main_window(app: &AppHandle)", 1)[1].split("fn main()", 1)[0]
    assert "app.show()" in reveal
    assert "window.show()" in reveal
    assert "window.set_focus()" in reveal


def test_windows_and_linux_close_still_stop_the_backend_and_exit() -> None:
    source = (Path(__file__).parents[1] / "desktop/src-tauri/src/main.rs").read_text()
    window_events = source.split(".on_window_event", 1)[1]
    non_macos_close = window_events.split('#[cfg(not(target_os = "macos"))]', 1)[1]
    non_macos_close = non_macos_close.split(".build(tauri::generate_context!())", 1)[0]

    assert "api.prevent_close();" in non_macos_close
    assert "stop_backend(&window.app_handle());" in non_macos_close
    assert "window.app_handle().exit(0);" in non_macos_close


def test_backend_startup_and_window_failures_reap_the_child_process() -> None:
    source = (Path(__file__).parents[1] / "desktop/src-tauri/src/main.rs").read_text()

    assert "fn terminate_child(child: &mut Child)" in source
    assert "let _ = child.wait();" in source
    assert "terminate_child(&mut child);\n            return Err(error);" in source
    assert (
        "if let Err(error) = show_window(&app.handle(), url) {\n                        stop_backend(&app.handle());"
        in source
    )


def test_desktop_data_directory_can_be_isolated_for_native_testing() -> None:
    source = (Path(__file__).parents[1] / "desktop/src-tauri/src/main.rs").read_text()

    assert 'const DESKTOP_DATA_DIR_OVERRIDE: &str = "AQA_DESKTOP_DATA_DIR";' in source
    assert "desktop_data_dir_path(explicit)?" in source
    assert '.env("AQA_USER_DATA_DIR", data_dir)' in source
    assert '.env("PYTHONDONTWRITEBYTECODE", "1")' in source
    assert "must be an absolute path" in source
