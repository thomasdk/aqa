#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

#[cfg(target_os = "linux")]
use std::os::unix::process::CommandExt;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

use serde_json::Value;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu, HELP_SUBMENU_ID, WINDOW_SUBMENU_ID},
    AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_dialog::{DialogExt, FilePath};

const READY_PREFIX: &str = "AQA_DESKTOP_LISTEN ";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);
const DEFAULT_ZOOM_FACTOR: f64 = 1.0;
const MIN_ZOOM_FACTOR: f64 = 0.5;
const MAX_ZOOM_FACTOR: f64 = 4.0;
const ZOOM_STEP: f64 = 0.1;
const DESKTOP_PREFERENCES_FILE: &str = "desktop-shell-preferences.json";
const DESKTOP_DATA_DIR_OVERRIDE: &str = "AQA_DESKTOP_DATA_DIR";
const MENU_RELOAD: &str = "reload";
const MENU_ZOOM_IN: &str = "zoom-in";
const MENU_ZOOM_OUT: &str = "zoom-out";
const MENU_ACTUAL_SIZE: &str = "actual-size";
const MENU_ABOUT: &str = "about-aqa";
const SLEEP_INHIBITION_LEASE_TIMEOUT: Duration = Duration::from_secs(90);
#[cfg(any(target_os = "linux", test))]
const LINUX_SYSTEMD_INHIBIT_ARGS: [&str; 7] = [
    "--what=idle",
    "--who=AQA",
    "--why=Discussion generation is active",
    "--mode=block",
    "--no-ask-password",
    "sleep",
    "infinity",
];
#[cfg(any(target_os = "linux", test))]
const LINUX_INHIBITOR_SUPERVISOR: &str = concat!(
    "cleanup() { trap - TERM INT HUP EXIT; kill -TERM -- -$$ 2>/dev/null; }\n",
    "trap cleanup TERM INT HUP EXIT\n",
    "exec systemd-inhibit \"$@\" &\n",
    "wait $!\n"
);

struct Backend {
    child: Mutex<Option<Child>>,
    base_url: Mutex<Option<String>>,
    expected_exit: AtomicBool,
    log_path: PathBuf,
}

struct DesktopPreferences {
    zoom_factor: Mutex<f64>,
    path: PathBuf,
}

struct SleepInhibitionManager {
    state: Mutex<SleepInhibitionState>,
    shutdown: AtomicBool,
}

struct SleepInhibitionState {
    enabled: bool,
    active_operations: HashMap<String, Instant>,
    inhibitor: Option<PlatformSleepInhibitor>,
    acquisition_failed: bool,
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
struct PlatformSleepInhibitor {
    child: Child,
}

#[cfg(target_os = "windows")]
struct PlatformSleepInhibitor {
    stop_sender: mpsc::Sender<()>,
    worker: Option<thread::JoinHandle<()>>,
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
struct PlatformSleepInhibitor;

impl SleepInhibitionManager {
    fn new() -> Self {
        Self {
            state: Mutex::new(SleepInhibitionState {
                enabled: true,
                active_operations: HashMap::new(),
                inhibitor: None,
                acquisition_failed: false,
            }),
            shutdown: AtomicBool::new(false),
        }
    }

    fn update(&self, operation_id: String, active: bool, enabled: bool) -> Result<(), String> {
        let operation_id = operation_id.trim();
        if operation_id.is_empty() || operation_id.len() > 128 {
            return Err("sleep_inhibition_operation_id_invalid".to_string());
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| "sleep_inhibition_state_unavailable".to_string())?;
        if active {
            // Only an active/update call may change the global preference.
            // A late completion from another operation must not restore a
            // stale enabled value after the user toggled the setting.
            let should_retry_acquisition =
                !state.active_operations.contains_key(operation_id) || state.enabled != enabled;
            state.enabled = enabled;
            if should_retry_acquisition {
                state.acquisition_failed = false;
            }
            state
                .active_operations
                .insert(operation_id.to_string(), Instant::now());
        } else {
            state.active_operations.remove(operation_id);
        }
        state.reconcile()
    }

    fn reconcile(&self) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "sleep_inhibition_state_unavailable".to_string())?;
        state.expire_stale_operations(Instant::now());
        state.reconcile()
    }

    fn clear_operations(&self) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "sleep_inhibition_state_unavailable".to_string())?;
        state.active_operations.clear();
        state.reconcile()
    }

    fn shutdown(&self) {
        self.shutdown.store(true, Ordering::SeqCst);
        if let Ok(mut state) = self.state.lock() {
            state.enabled = false;
            state.active_operations.clear();
            let _ = state.reconcile();
        }
    }
}

impl SleepInhibitionState {
    fn should_inhibit(&self) -> bool {
        self.enabled && !self.active_operations.is_empty()
    }

    fn expire_stale_operations(&mut self, now: Instant) {
        self.active_operations.retain(|_, last_refresh| {
            now.saturating_duration_since(*last_refresh) < SLEEP_INHIBITION_LEASE_TIMEOUT
        });
    }

    fn reconcile(&mut self) -> Result<(), String> {
        if self
            .inhibitor
            .as_mut()
            .is_some_and(|inhibitor| !inhibitor.is_active())
        {
            self.inhibitor.take();
        }

        let should_inhibit = self.should_inhibit();
        match (should_inhibit, self.inhibitor.is_some()) {
            (true, false) if !self.acquisition_failed => match PlatformSleepInhibitor::acquire() {
                Ok(inhibitor) => self.inhibitor = Some(inhibitor),
                Err(error) => {
                    self.acquisition_failed = true;
                    return Err(error);
                }
            },
            (false, true) => {
                if let Some(mut inhibitor) = self.inhibitor.take() {
                    inhibitor.release()?;
                }
            }
            _ => {}
        }
        Ok(())
    }
}

#[cfg(target_os = "macos")]
impl PlatformSleepInhibitor {
    fn acquire() -> Result<Self, String> {
        let arguments = macos_caffeinate_arguments(std::process::id());
        let mut child = Command::new("/usr/bin/caffeinate")
            .args(arguments)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "sleep_inhibition_unavailable".to_string())?;
        thread::sleep(Duration::from_millis(50));
        if child.try_wait().ok().flatten().is_some() {
            return Err("sleep_inhibition_unavailable".to_string());
        }
        Ok(Self { child })
    }

    fn is_active(&mut self) -> bool {
        self.child.try_wait().ok().flatten().is_none()
    }

    fn release(&mut self) -> Result<(), String> {
        if self.is_active() {
            self.child
                .kill()
                .map_err(|_| "sleep_inhibition_release_failed".to_string())?;
        }
        self.child
            .wait()
            .map_err(|_| "sleep_inhibition_release_failed".to_string())?;
        Ok(())
    }
}

#[cfg(any(target_os = "macos", test))]
fn macos_caffeinate_arguments(aqa_pid: u32) -> [String; 3] {
    ["-i".to_string(), "-w".to_string(), aqa_pid.to_string()]
}

#[cfg(target_os = "linux")]
impl PlatformSleepInhibitor {
    fn acquire() -> Result<Self, String> {
        let parent_pid = unsafe { libc::getpid() };
        let mut command = Command::new("/bin/sh");
        command
            .arg("-c")
            .arg(LINUX_INHIBITOR_SUPERVISOR)
            .arg("aqa-sleep-inhibitor")
            .args(LINUX_SYSTEMD_INHIBIT_ARGS)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        // Give the inhibitor and its payload a private process group so both
        // are terminated together and no helper survives application exit.
        unsafe {
            command.pre_exec(move || {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                // PR_SET_PDEATHSIG is not retroactive. Detect a parent that
                // exited between fork and prctl before exec starts helpers.
                if linux_parent_changed(parent_pid, libc::getppid()) {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::Interrupted,
                        "sleep inhibitor parent exited during startup",
                    ));
                }
                Ok(())
            });
        }
        let mut child = command
            .spawn()
            .map_err(|_| "sleep_inhibition_unavailable".to_string())?;
        thread::sleep(Duration::from_millis(100));
        if child.try_wait().ok().flatten().is_some() {
            return Err("sleep_inhibition_unavailable".to_string());
        }
        Ok(Self { child })
    }

    fn is_active(&mut self) -> bool {
        self.child.try_wait().ok().flatten().is_none()
    }

    fn release(&mut self) -> Result<(), String> {
        if self.is_active() {
            let result = unsafe { libc::kill(-(self.child.id() as i32), libc::SIGTERM) };
            if result == -1 {
                return Err("sleep_inhibition_release_failed".to_string());
            }
        }
        self.child
            .wait()
            .map_err(|_| "sleep_inhibition_release_failed".to_string())?;
        Ok(())
    }
}

#[cfg(any(target_os = "linux", test))]
fn linux_parent_changed(expected_parent: i32, actual_parent: i32) -> bool {
    expected_parent != actual_parent
}

#[cfg(target_os = "windows")]
impl PlatformSleepInhibitor {
    fn acquire() -> Result<Self, String> {
        use windows_sys::Win32::System::Power::{
            SetThreadExecutionState, ES_CONTINUOUS, ES_SYSTEM_REQUIRED,
        };

        let (started_sender, started_receiver) = mpsc::sync_channel(1);
        let (stop_sender, stop_receiver) = mpsc::channel();
        let worker = thread::spawn(move || {
            let result = unsafe { SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) };
            let _ = started_sender.send(result != 0);
            if result != 0 {
                let _ = stop_receiver.recv();
                unsafe {
                    SetThreadExecutionState(ES_CONTINUOUS);
                }
            }
        });
        match started_receiver.recv_timeout(Duration::from_secs(2)) {
            Ok(true) => Ok(Self {
                stop_sender,
                worker: Some(worker),
            }),
            _ => {
                let _ = stop_sender.send(());
                let _ = worker.join();
                Err("sleep_inhibition_unavailable".to_string())
            }
        }
    }

    fn is_active(&mut self) -> bool {
        self.worker
            .as_ref()
            .is_some_and(|worker| !worker.is_finished())
    }

    fn release(&mut self) -> Result<(), String> {
        let _ = self.stop_sender.send(());
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| "sleep_inhibition_release_failed".to_string())?;
        }
        Ok(())
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
impl PlatformSleepInhibitor {
    fn acquire() -> Result<Self, String> {
        Err("sleep_inhibition_unsupported".to_string())
    }

    fn is_active(&mut self) -> bool {
        false
    }

    fn release(&mut self) -> Result<(), String> {
        Ok(())
    }
}

impl Drop for PlatformSleepInhibitor {
    fn drop(&mut self) {
        let _ = self.release();
    }
}

#[tauri::command]
fn update_generation_sleep_inhibition(
    app: AppHandle,
    operation_id: String,
    active: bool,
    enabled: bool,
) -> Result<(), String> {
    app.state::<SleepInhibitionManager>()
        .update(operation_id, active, enabled)
}

fn monitor_sleep_inhibition(app: AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(2));
        let manager = app.state::<SleepInhibitionManager>();
        if manager.shutdown.load(Ordering::SeqCst) {
            return;
        }
        if let Err(code) = manager.reconcile() {
            eprintln!("AQA sleep inhibition diagnostic: {code}");
        }
    });
}

fn stop_sleep_inhibition(app: &AppHandle) {
    app.state::<SleepInhibitionManager>().shutdown();
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ViewMenuAction {
    About,
    Reload,
    ZoomIn,
    ZoomOut,
    ActualSize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NativeMenuLocale {
    English,
    German,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NativeMenuLabel {
    File,
    Edit,
    View,
    Window,
    Help,
    Refresh,
    ActualSize,
    ZoomIn,
    ZoomOut,
    About,
    #[cfg(target_os = "macos")]
    Services,
    #[cfg(target_os = "macos")]
    Hide,
    #[cfg(target_os = "macos")]
    HideOthers,
    Quit,
    CloseWindow,
    Minimize,
    Maximize,
    #[cfg(target_os = "macos")]
    Fullscreen,
    Undo,
    Redo,
    Cut,
    Copy,
    Paste,
    SelectAll,
}

fn native_menu_label(locale: NativeMenuLocale, label: NativeMenuLabel) -> &'static str {
    use NativeMenuLabel::*;

    match (locale, label) {
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, File) => "Ablage",
        #[cfg(not(target_os = "macos"))]
        (NativeMenuLocale::German, File) => "Datei",
        (NativeMenuLocale::German, Edit) => "Bearbeiten",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, View) => "Darstellung",
        #[cfg(not(target_os = "macos"))]
        (NativeMenuLocale::German, View) => "Ansicht",
        (NativeMenuLocale::German, Window) => "Fenster",
        (NativeMenuLocale::German, Help) => "Hilfe",
        (NativeMenuLocale::German, Refresh) => "Aktualisieren",
        (NativeMenuLocale::German, ActualSize) => "Originalgröße",
        (NativeMenuLocale::German, ZoomIn) => "Vergrößern",
        (NativeMenuLocale::German, ZoomOut) => "Verkleinern",
        (NativeMenuLocale::German, About) => "Über AQA",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, Services) => "Dienste",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, Hide) => "AQA ausblenden",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, HideOthers) => "Andere ausblenden",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, Quit) => "AQA beenden",
        #[cfg(not(target_os = "macos"))]
        (NativeMenuLocale::German, Quit) => "Beenden",
        #[cfg(target_os = "windows")]
        (NativeMenuLocale::German, CloseWindow) => "Schließen",
        #[cfg(not(target_os = "windows"))]
        (NativeMenuLocale::German, CloseWindow) => "Fenster schließen",
        (NativeMenuLocale::German, Minimize) => "Minimieren",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, Maximize) => "Zoomen",
        #[cfg(not(target_os = "macos"))]
        (NativeMenuLocale::German, Maximize) => "Maximieren",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::German, Fullscreen) => "Vollbild aktivieren",
        (NativeMenuLocale::German, Undo) => "Widerrufen",
        (NativeMenuLocale::German, Redo) => "Wiederholen",
        (NativeMenuLocale::German, Cut) => "Ausschneiden",
        (NativeMenuLocale::German, Copy) => "Kopieren",
        (NativeMenuLocale::German, Paste) => "Einsetzen",
        (NativeMenuLocale::German, SelectAll) => "Alles auswählen",
        (NativeMenuLocale::English, File) => "File",
        (NativeMenuLocale::English, Edit) => "Edit",
        (NativeMenuLocale::English, View) => "View",
        (NativeMenuLocale::English, Window) => "Window",
        (NativeMenuLocale::English, Help) => "Help",
        (NativeMenuLocale::English, Refresh) => "Refresh",
        (NativeMenuLocale::English, ActualSize) => "Actual Size",
        (NativeMenuLocale::English, ZoomIn) => "Zoom In",
        (NativeMenuLocale::English, ZoomOut) => "Zoom Out",
        (NativeMenuLocale::English, About) => "About AQA",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::English, Services) => "Services",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::English, Hide) => "Hide AQA",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::English, HideOthers) => "Hide Others",
        #[cfg(target_os = "windows")]
        (NativeMenuLocale::English, Quit) => "Exit",
        #[cfg(not(target_os = "windows"))]
        (NativeMenuLocale::English, Quit) => "Quit AQA",
        #[cfg(target_os = "windows")]
        (NativeMenuLocale::English, CloseWindow) => "Close",
        #[cfg(not(target_os = "windows"))]
        (NativeMenuLocale::English, CloseWindow) => "Close Window",
        (NativeMenuLocale::English, Minimize) => "Minimize",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::English, Maximize) => "Zoom",
        #[cfg(not(target_os = "macos"))]
        (NativeMenuLocale::English, Maximize) => "Maximize",
        #[cfg(target_os = "macos")]
        (NativeMenuLocale::English, Fullscreen) => "Toggle Full Screen",
        (NativeMenuLocale::English, Undo) => "Undo",
        (NativeMenuLocale::English, Redo) => "Redo",
        (NativeMenuLocale::English, Cut) => "Cut",
        (NativeMenuLocale::English, Copy) => "Copy",
        (NativeMenuLocale::English, Paste) => "Paste",
        (NativeMenuLocale::English, SelectAll) => "Select All",
    }
}

fn native_menu_locale_for_language_code(language_code: &str) -> NativeMenuLocale {
    let language = language_code
        .split(['-', '_'])
        .next()
        .unwrap_or(language_code);
    if language.eq_ignore_ascii_case("de") {
        NativeMenuLocale::German
    } else {
        NativeMenuLocale::English
    }
}

fn parse_native_menu_locale(locale: &str) -> Result<NativeMenuLocale, String> {
    let normalized = locale.trim().to_ascii_lowercase();
    let language = normalized
        .split(['-', '_'])
        .next()
        .unwrap_or(normalized.as_str());
    if matches!(language, "de" | "en") {
        Ok(native_menu_locale_for_language_code(&normalized))
    } else {
        Err(format!("unsupported native menu locale: {locale}"))
    }
}

#[tauri::command]
fn set_native_menu_locale(app: AppHandle, locale: String) -> Result<(), String> {
    // Menu copy belongs to the AQA locale; file and folder dialogs stay in
    // tauri-plugin-dialog so their controls remain OS-locale-owned.
    let locale = parse_native_menu_locale(&locale)?;
    install_menu(&app, locale)
        .map_err(|error| format!("cannot update native application menu: {error}"))
}

impl ViewMenuAction {
    fn from_menu_id(id: &str) -> Option<Self> {
        match id {
            MENU_ABOUT => Some(Self::About),
            MENU_RELOAD => Some(Self::Reload),
            MENU_ZOOM_IN => Some(Self::ZoomIn),
            MENU_ZOOM_OUT => Some(Self::ZoomOut),
            MENU_ACTUAL_SIZE => Some(Self::ActualSize),
            _ => None,
        }
    }
}

impl Backend {
    fn new(log_path: PathBuf) -> Self {
        Self {
            child: Mutex::new(None),
            base_url: Mutex::new(None),
            expected_exit: AtomicBool::new(false),
            log_path,
        }
    }
}

fn desktop_data_dir_path(explicit: Option<PathBuf>) -> Result<PathBuf, String> {
    if let Some(path) = explicit {
        if !path.is_absolute() {
            return Err(format!(
                "{DESKTOP_DATA_DIR_OVERRIDE} must be an absolute path"
            ));
        }
        return Ok(path);
    }
    #[cfg(target_os = "macos")]
    let path = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or("HOME is unavailable")?
        .join("Library/Application Support/AQA");
    #[cfg(target_os = "windows")]
    let path = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or("LOCALAPPDATA is unavailable")?
        .join("AQA");
    #[cfg(all(unix, not(target_os = "macos")))]
    let path = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))
        .ok_or("XDG_DATA_HOME and HOME are unavailable")?
        .join("aqa");
    Ok(path)
}

fn desktop_data_dir() -> Result<PathBuf, String> {
    let explicit = std::env::var_os(DESKTOP_DATA_DIR_OVERRIDE)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from);
    let path = desktop_data_dir_path(explicit)?;
    fs::create_dir_all(&path)
        .map_err(|error| format!("cannot create app data directory: {error}"))?;
    Ok(path)
}

fn valid_markdown_export_filename(filename: &str) -> bool {
    let Some(stem) = filename.strip_suffix(".md") else {
        return false;
    };
    !stem.is_empty()
        && stem.len() <= 120
        && stem
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
}

fn write_markdown_export(path: Option<FilePath>, contents: &str) -> Result<Option<String>, String> {
    let Some(path) = path else {
        return Ok(None);
    };
    let path = path
        .into_path()
        .map_err(|error| format!("cannot resolve export path: {error}"))?;
    fs::write(&path, contents).map_err(|error| format!("cannot save Markdown export: {error}"))?;
    let filename = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "saved Markdown filename is not valid UTF-8".to_string())?;
    Ok(Some(filename.to_string()))
}

#[tauri::command]
async fn save_markdown_export(
    app: AppHandle,
    suggested_filename: String,
    contents: String,
) -> Result<Option<String>, String> {
    if !valid_markdown_export_filename(&suggested_filename) {
        return Err("invalid Markdown export filename".to_string());
    }
    let selected_path = app
        .dialog()
        .file()
        .add_filter("Markdown", &["md"])
        .set_file_name(suggested_filename)
        .blocking_save_file();
    write_markdown_export(selected_path, &contents)
}

fn resolve_picked_directory(path: Option<FilePath>) -> Result<Option<String>, String> {
    let Some(path) = path else {
        return Ok(None);
    };
    let path = path
        .into_path()
        .map_err(|error| format!("cannot resolve import directory: {error}"))?;
    if !path.is_dir() {
        return Err("selected Local AI import path is not a directory".to_string());
    }
    path.to_str()
        .map(|value| Some(value.to_string()))
        .ok_or_else(|| "selected Local AI import directory is not valid UTF-8".to_string())
}

#[tauri::command]
async fn pick_local_ai_import_directory(app: AppHandle) -> Result<Option<String>, String> {
    let selected_path = app.dialog().file().blocking_pick_folder();
    resolve_picked_directory(selected_path)
}

fn safe_session_file_id(file_id: &str) -> bool {
    !file_id.is_empty()
        && !file_id.starts_with('.')
        && file_id != "."
        && file_id != ".."
        && file_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "._-".contains(character))
}

fn resolve_managed_path(
    data_root: &std::path::Path,
    kind: &str,
    file_id: Option<&str>,
) -> Result<(PathBuf, bool), String> {
    let (candidate, reveal_file) = match kind {
        "session" => {
            let file_id = file_id.ok_or("session file id is required")?;
            if !safe_session_file_id(file_id) {
                return Err("invalid session file id".to_string());
            }
            (
                data_root
                    .join("conversations")
                    .join(format!("{file_id}.json")),
                true,
            )
        }
        "local_ai_models" => (data_root.join("local-ai/models"), false),
        "perspectives" => (data_root.join("prompts/roles"), false),
        "session_types" => (data_root.join("prompts/session_contexts"), false),
        "prompt_library" => (data_root.join("prompts"), false),
        _ => return Err("unknown managed path kind".to_string()),
    };
    let canonical = candidate
        .canonicalize()
        .map_err(|_| "managed path is unavailable".to_string())?;
    let canonical_root = data_root
        .canonicalize()
        .map_err(|_| "desktop data directory is unavailable".to_string())?;
    if !canonical.starts_with(&canonical_root)
        || (reveal_file && !canonical.is_file())
        || (!reveal_file && !canonical.is_dir())
    {
        return Err("managed path is unavailable".to_string());
    }
    Ok((canonical, reveal_file))
}

fn reveal_path_with_system(path: &std::path::Path, reveal_file: bool) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        if reveal_file {
            command.arg("-R");
        }
        command.arg(path);
        command
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("explorer");
        if reveal_file {
            command.arg(format!("/select,{}", path.display()));
        } else {
            command.arg(path);
        }
        command
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(if reveal_file {
            path.parent().unwrap_or(path)
        } else {
            path
        });
        command
    };
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("cannot reveal managed path: {error}"))
}

#[tauri::command]
async fn reveal_managed_path(kind: String, file_id: Option<String>) -> Result<(), String> {
    let data_root = desktop_data_dir()?;
    let (path, reveal_file) = resolve_managed_path(&data_root, &kind, file_id.as_deref())?;
    reveal_path_with_system(&path, reveal_file)
}

fn valid_zoom_factor(value: f64) -> Option<f64> {
    (value.is_finite() && (MIN_ZOOM_FACTOR..=MAX_ZOOM_FACTOR).contains(&value)).then_some(value)
}

fn rounded_zoom_factor(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

fn next_zoom_factor(current: f64, direction: f64) -> f64 {
    let base = valid_zoom_factor(current).unwrap_or(DEFAULT_ZOOM_FACTOR);
    rounded_zoom_factor((base + direction * ZOOM_STEP).clamp(MIN_ZOOM_FACTOR, MAX_ZOOM_FACTOR))
}

fn parse_zoom_factor(source: &str) -> f64 {
    serde_json::from_str::<Value>(source)
        .ok()
        .and_then(|value| value.get("zoom_factor").and_then(Value::as_f64))
        .and_then(valid_zoom_factor)
        .unwrap_or(DEFAULT_ZOOM_FACTOR)
}

fn load_desktop_preferences(path: PathBuf) -> DesktopPreferences {
    let zoom_factor = fs::read_to_string(&path)
        .ok()
        .map(|source| parse_zoom_factor(&source))
        .unwrap_or(DEFAULT_ZOOM_FACTOR);
    DesktopPreferences {
        zoom_factor: Mutex::new(zoom_factor),
        path,
    }
}

fn persist_zoom_factor(preferences: &DesktopPreferences, zoom_factor: f64) -> Result<(), String> {
    let contents = serde_json::json!({ "zoom_factor": zoom_factor }).to_string();
    fs::write(&preferences.path, contents)
        .map_err(|error| format!("cannot save desktop zoom preference: {error}"))
}

fn apply_zoom(app: &AppHandle, zoom_factor: f64) {
    let Some(zoom_factor) = valid_zoom_factor(zoom_factor) else {
        return;
    };
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    if window.set_zoom(zoom_factor).is_err() {
        return;
    }
    let preferences = app.state::<DesktopPreferences>();
    if let Ok(mut stored_zoom) = preferences.zoom_factor.lock() {
        *stored_zoom = zoom_factor;
    }
    let _ = persist_zoom_factor(&preferences, zoom_factor);
}

fn append_view_menu_items(
    app: &AppHandle,
    view: &Submenu<tauri::Wry>,
    locale: NativeMenuLocale,
) -> tauri::Result<()> {
    let refresh = MenuItem::with_id(
        app,
        MENU_RELOAD,
        native_menu_label(locale, NativeMenuLabel::Refresh),
        true,
        Some("CmdOrCtrl+R"),
    )?;
    let separator = PredefinedMenuItem::separator(app)?;
    let actual_size = MenuItem::with_id(
        app,
        MENU_ACTUAL_SIZE,
        native_menu_label(locale, NativeMenuLabel::ActualSize),
        true,
        Some("CmdOrCtrl+0"),
    )?;
    let zoom_in = MenuItem::with_id(
        app,
        MENU_ZOOM_IN,
        native_menu_label(locale, NativeMenuLabel::ZoomIn),
        true,
        Some("CmdOrCtrl+="),
    )?;
    let zoom_out = MenuItem::with_id(
        app,
        MENU_ZOOM_OUT,
        native_menu_label(locale, NativeMenuLabel::ZoomOut),
        true,
        Some("CmdOrCtrl+-"),
    )?;
    view.append(&refresh)?;
    view.append(&separator)?;
    view.append(&actual_size)?;
    view.append(&zoom_in)?;
    view.append(&zoom_out)?;
    Ok(())
}

fn build_native_menu(app: &AppHandle, locale: NativeMenuLocale) -> tauri::Result<Menu<tauri::Wry>> {
    let package = app.package_info();
    let about = MenuItem::with_id(
        app,
        MENU_ABOUT,
        native_menu_label(locale, NativeMenuLabel::About),
        true,
        None::<&str>,
    )?;

    let window = Submenu::with_id_and_items(
        app,
        WINDOW_SUBMENU_ID,
        native_menu_label(locale, NativeMenuLabel::Window),
        true,
        &[
            &PredefinedMenuItem::minimize(
                app,
                Some(native_menu_label(locale, NativeMenuLabel::Minimize)),
            )?,
            &PredefinedMenuItem::maximize(
                app,
                Some(native_menu_label(locale, NativeMenuLabel::Maximize)),
            )?,
            #[cfg(target_os = "macos")]
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(
                app,
                Some(native_menu_label(locale, NativeMenuLabel::CloseWindow)),
            )?,
        ],
    )?;
    let help = Submenu::with_id_and_items(
        app,
        HELP_SUBMENU_ID,
        native_menu_label(locale, NativeMenuLabel::Help),
        true,
        &[
            #[cfg(not(target_os = "macos"))]
            &about,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        native_menu_label(locale, NativeMenuLabel::View),
        true,
        &[
            #[cfg(target_os = "macos")]
            &PredefinedMenuItem::fullscreen(
                app,
                Some(native_menu_label(locale, NativeMenuLabel::Fullscreen)),
            )?,
        ],
    )?;
    #[cfg(target_os = "macos")]
    view.append(&PredefinedMenuItem::separator(app)?)?;
    append_view_menu_items(app, &view, locale)?;

    Menu::with_items(
        app,
        &[
            #[cfg(target_os = "macos")]
            &Submenu::with_items(
                app,
                package.name.clone(),
                true,
                &[
                    &about,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::services(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Services)),
                    )?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::hide(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Hide)),
                    )?,
                    &PredefinedMenuItem::hide_others(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::HideOthers)),
                    )?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::quit(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Quit)),
                    )?,
                ],
            )?,
            #[cfg(not(any(
                target_os = "linux",
                target_os = "dragonfly",
                target_os = "freebsd",
                target_os = "netbsd",
                target_os = "openbsd"
            )))]
            &Submenu::with_items(
                app,
                native_menu_label(locale, NativeMenuLabel::File),
                true,
                &[
                    &PredefinedMenuItem::close_window(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::CloseWindow)),
                    )?,
                    #[cfg(not(target_os = "macos"))]
                    &PredefinedMenuItem::quit(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Quit)),
                    )?,
                ],
            )?,
            &Submenu::with_items(
                app,
                native_menu_label(locale, NativeMenuLabel::Edit),
                true,
                &[
                    &PredefinedMenuItem::undo(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Undo)),
                    )?,
                    &PredefinedMenuItem::redo(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Redo)),
                    )?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::cut(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Cut)),
                    )?,
                    &PredefinedMenuItem::copy(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Copy)),
                    )?,
                    &PredefinedMenuItem::paste(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::Paste)),
                    )?,
                    &PredefinedMenuItem::select_all(
                        app,
                        Some(native_menu_label(locale, NativeMenuLabel::SelectAll)),
                    )?,
                ],
            )?,
            &view,
            &window,
            &help,
        ],
    )
}

fn install_menu(app: &AppHandle, locale: NativeMenuLocale) -> tauri::Result<()> {
    let menu = build_native_menu(app, locale)?;
    app.set_menu(menu)?;
    Ok(())
}

fn handle_view_menu_action(app: &AppHandle, action: ViewMenuAction) {
    match action {
        ViewMenuAction::About => {
            reveal_main_window(app);
            if let Some(window) = app.get_webview_window("main") {
                if let Ok(mut url) = window.url() {
                    url.set_fragment(Some("aqa-about"));
                    let _ = window.navigate(url);
                }
            }
        }
        ViewMenuAction::Reload => {
            if let Err(code) = app.state::<SleepInhibitionManager>().clear_operations() {
                eprintln!("AQA sleep inhibition diagnostic: {code}");
            }
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.reload();
            }
        }
        ViewMenuAction::ActualSize => apply_zoom(app, DEFAULT_ZOOM_FACTOR),
        ViewMenuAction::ZoomIn | ViewMenuAction::ZoomOut => {
            let preferences = app.state::<DesktopPreferences>();
            let current = preferences
                .zoom_factor
                .lock()
                .map(|value| *value)
                .unwrap_or(DEFAULT_ZOOM_FACTOR);
            let direction = if action == ViewMenuAction::ZoomIn {
                1.0
            } else {
                -1.0
            };
            apply_zoom(app, next_zoom_factor(current, direction));
        }
    }
}

fn backend_root(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resolve("resources/backend", tauri::path::BaseDirectory::Resource)
        .map_err(|error| format!("cannot find bundled backend: {error}"))
}

fn python_path(root: &std::path::Path) -> PathBuf {
    #[cfg(target_os = "windows")]
    return root.join("runtime/python.exe");
    #[cfg(not(target_os = "windows"))]
    root.join("runtime/bin/python3")
}

fn parse_ready_line(line: &str) -> Result<Option<u16>, String> {
    let Some(json) = line.strip_prefix(READY_PREFIX) else {
        return Ok(None);
    };
    let value: Value =
        serde_json::from_str(json).map_err(|_| "malformed backend readiness output".to_string())?;
    let host = value.get("host").and_then(Value::as_str);
    let port = value.get("port").and_then(Value::as_u64);
    match (host, port) {
        (Some("127.0.0.1"), Some(port @ 1..=65535)) => Ok(Some(port as u16)),
        _ => Err("backend readiness record was not loopback with a valid port".to_string()),
    }
}

fn drain_backend_stdout<R: BufRead>(stdout: R, sender: mpsc::SyncSender<String>) -> usize {
    let mut forward_readiness = true;
    let mut lines_drained = 0;
    for line in stdout.lines() {
        lines_drained += 1;
        if forward_readiness && sender.send(line.unwrap_or_default()).is_err() {
            // The startup receiver is intentionally short-lived, but the backend
            // keeps stdout open for access logs. Continue draining the pipe so a
            // busy backend cannot block or fail with BrokenPipe.
            forward_readiness = false;
        }
    }
    lines_drained
}

fn health_is_ready(port: u16) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}")
            .parse()
            .expect("static socket address is valid"),
        Duration::from_secs(2),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream
        .write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok() && response.starts_with("HTTP/1.1 200")
}

fn endpoint_response(port: u16, request: String) -> Option<String> {
    let mut stream = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().ok()?,
        Duration::from_secs(3),
    )
    .ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(3))).ok()?;
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = String::new();
    stream.read_to_string(&mut response).ok()?;
    Some(response)
}

fn request_graceful_quit(port: u16) {
    let status = endpoint_response(
        port,
        "GET /api/application/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            .to_string(),
    );
    let token = status
        .as_deref()
        .and_then(|body| body.split("\r\n\r\n").nth(1))
        .and_then(|body| serde_json::from_str::<Value>(body).ok())
        .and_then(|value| {
            value
                .get("quit_token")
                .and_then(Value::as_str)
                .map(str::to_owned)
        });
    if let Some(token) = token {
        let request = format!("POST /api/application/quit HTTP/1.1\r\nHost: 127.0.0.1\r\nX-AQA-Action: {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        let _ = endpoint_response(port, request);
    }
}

fn open_external(url: &str) {
    #[cfg(target_os = "macos")]
    let _ = Command::new("open").arg(url).spawn();
    #[cfg(target_os = "windows")]
    {
        let mut command = Command::new("cmd");
        command.args(["/C", "start", "", url]);
        hide_windows_console(&mut command);
        let _ = command.spawn();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    let _ = Command::new("xdg-open").arg(url).spawn();
}

#[cfg(target_os = "windows")]
fn hide_windows_console(command: &mut Command) {
    // A GUI-subsystem parent does not prevent a console-subsystem child from
    // allocating its own window. Keep its process handle and redirected pipes.
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

fn fail(app: &AppHandle, backend: &Backend, reason: &str) {
    app.dialog()
        .message(format!(
            "AQA could not start.\n\n{reason}\n\nDiagnostic log: {}",
            backend.log_path.display()
        ))
        .title("AQA")
        .blocking_show();
}

fn terminate_child(child: &mut Child) {
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.kill();
    }
    let _ = child.wait();
}

fn start_backend(app: &AppHandle) -> Result<String, String> {
    let data_dir = desktop_data_dir()?;
    let log_dir = data_dir.join("logs");
    fs::create_dir_all(&log_dir)
        .map_err(|error| format!("cannot create log directory: {error}"))?;
    let log_path = log_dir.join("desktop-backend.log");
    app.manage(Backend::new(log_path.clone()));
    let root = backend_root(app)?;
    let python = python_path(&root);
    if !python.is_file() {
        return Err(format!("bundled Python is missing: {}", python.display()));
    }
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("cannot open backend log: {error}"))?;
    let mut command = Command::new(python);
    #[cfg(target_os = "windows")]
    hide_windows_console(&mut command);
    command
        .current_dir(&root)
        .arg("-m")
        .arg("src.desktop_server")
        .env("AQA_PACKAGED_MODE", "1")
        .env("AQA_USER_DATA_DIR", data_dir)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("API_HOST", "127.0.0.1")
        .env("API_PORT", "0")
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log));
    for key in [
        "PYTHONPATH",
        "AQA_SETTINGS_PATH",
        "AQA_CONVERSATIONS_DIR",
        "PROMPT_LIBRARY_PATH",
        "PROMPT_DEFAULTS_PATH",
        "AQA_LOCAL_AI_DIR",
        "AQA_PROMPT_DEFAULTS_DIR",
        "AQA_SYNC_PROMPTS_FROM_SOURCE",
    ] {
        command.env_remove(key);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("cannot start bundled backend: {error}"))?;
    let startup = (|| -> Result<u16, String> {
        let stdout = child
            .stdout
            .take()
            .ok_or("cannot capture backend readiness output")?;
        let (sender, receiver) = mpsc::sync_channel(16);
        thread::spawn(move || drain_backend_stdout(BufReader::new(stdout), sender));
        let deadline = Instant::now() + STARTUP_TIMEOUT;
        let port = loop {
            if let Some(status) = child
                .try_wait()
                .map_err(|error| format!("cannot observe backend: {error}"))?
            {
                return Err(format!("backend exited before readiness ({status})"));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err("backend readiness timed out".to_string());
            }
            match receiver.recv_timeout(remaining.min(Duration::from_millis(250))) {
                Ok(line) => match parse_ready_line(&line) {
                    Ok(Some(port)) => break port,
                    Ok(None) => {}
                    Err(error) => return Err(error),
                },
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    return Err("backend closed readiness output".to_string());
                }
            }
        };
        drop(receiver);
        let health_deadline = Instant::now() + HEALTH_TIMEOUT;
        while !health_is_ready(port) {
            if child.try_wait().ok().flatten().is_some() {
                return Err("backend exited before becoming healthy".to_string());
            }
            if Instant::now() >= health_deadline {
                return Err("backend health check timed out".to_string());
            }
            thread::sleep(Duration::from_millis(200));
        }
        Ok(port)
    })();
    let port = match startup {
        Ok(port) => port,
        Err(error) => {
            terminate_child(&mut child);
            return Err(error);
        }
    };
    let backend = app.state::<Backend>();
    let mut child_guard = match backend.child.lock() {
        Ok(child_guard) => child_guard,
        Err(_) => {
            terminate_child(&mut child);
            return Err("backend process lock failed".to_string());
        }
    };
    *child_guard = Some(child);
    drop(child_guard);
    let base_url = format!("http://127.0.0.1:{port}");
    let mut base_url_guard = match backend.base_url.lock() {
        Ok(base_url_guard) => base_url_guard,
        Err(_) => {
            stop_backend(app);
            return Err("backend URL lock failed".to_string());
        }
    };
    *base_url_guard = Some(base_url.clone());
    Ok(base_url)
}

fn monitor_backend(app: AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(300));
        let backend = app.state::<Backend>();
        let exited = backend.child.lock().ok().and_then(|mut child| {
            child
                .as_mut()
                .and_then(|child| child.try_wait().ok().flatten())
        });
        if let Some(status) = exited {
            if !backend.expected_exit.load(Ordering::SeqCst) {
                fail(
                    &app,
                    &backend,
                    &format!("The local backend stopped unexpectedly ({status})."),
                );
                app.exit(1);
            }
            return;
        }
    });
}

fn appearance_theme(appearance: &str) -> Result<Option<tauri::Theme>, String> {
    match appearance {
        "system" => Ok(None),
        "light" => Ok(Some(tauri::Theme::Light)),
        "dark" => Ok(Some(tauri::Theme::Dark)),
        _ => Err("invalid appearance preference".into()),
    }
}

#[tauri::command]
fn set_native_appearance(app: AppHandle, appearance: String) -> Result<(), String> {
    let theme = appearance_theme(&appearance)?;
    let window = app
        .get_webview_window("main")
        .ok_or("main window is unavailable")?;
    window.set_theme(theme).map_err(|error| error.to_string())
}

fn show_window(app: &AppHandle, base_url: String) -> Result<(), String> {
    let allowed_origin = base_url.clone();
    let allowed_prefix = format!("{base_url}/");
    let builder = WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::External(
            base_url
                .parse()
                .map_err(|e| format!("invalid loopback URL: {e}"))?,
        ),
    )
    .title("AQA");
    #[cfg(target_os = "macos")]
    let builder = builder.hidden_title(true);
    let window = builder
        .inner_size(1280.0, 860.0)
        .min_inner_size(960.0, 640.0)
        .visible(false)
        .on_navigation(move |url| {
            if url.as_str() == allowed_origin || url.as_str().starts_with(&allowed_prefix) {
                true
            } else if matches!(url.scheme(), "http" | "https") {
                open_external(url.as_str());
                false
            } else {
                false
            }
        })
        .build()
        .map_err(|error| format!("cannot create desktop window: {error}"))?;
    let zoom_factor = app
        .state::<DesktopPreferences>()
        .zoom_factor
        .lock()
        .map(|value| *value)
        .unwrap_or(DEFAULT_ZOOM_FACTOR);
    window
        .set_zoom(zoom_factor)
        .map_err(|error| format!("cannot restore desktop zoom: {error}"))?;
    window
        .show()
        .map_err(|error| format!("cannot reveal desktop window: {error}"))?;
    Ok(())
}

fn stop_backend(app: &AppHandle) {
    let backend = app.state::<Backend>();
    backend.expected_exit.store(true, Ordering::SeqCst);
    if let Ok(Some(url)) = backend.base_url.lock().map(|url| url.clone()) {
        if let Some(port) = url.rsplit(':').next().and_then(|port| port.parse().ok()) {
            request_graceful_quit(port);
        }
    }
    let Ok(mut child_guard) = backend.child.lock() else {
        return;
    };
    let Some(mut child) = child_guard.take() else {
        return;
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    terminate_child(&mut child);
}

fn reveal_main_window(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    let _ = app.show();
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg(target_os = "macos")]
async fn receive_notification_callback<T: Send + 'static>(
    receiver: mpsc::Receiver<T>,
    timeout_error: &'static str,
    task_error: &'static str,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(move || {
        receiver
            .recv_timeout(Duration::from_secs(30))
            .map_err(|_| timeout_error.to_string())
    })
    .await
    .map_err(|_| task_error.to_string())?
}

#[cfg(target_os = "macos")]
fn notification_permission_name(
    status: objc2_user_notifications::UNAuthorizationStatus,
) -> &'static str {
    use objc2_user_notifications::UNAuthorizationStatus;

    match status {
        UNAuthorizationStatus::Authorized
        | UNAuthorizationStatus::Provisional
        | UNAuthorizationStatus::Ephemeral => "granted",
        UNAuthorizationStatus::Denied => "denied",
        _ => "default",
    }
}

#[cfg(target_os = "macos")]
fn notification_permission_state_receiver() -> mpsc::Receiver<String> {
    use block2::RcBlock;
    use objc2_user_notifications::{UNNotificationSettings, UNUserNotificationCenter};
    use std::ptr::NonNull;

    let center = UNUserNotificationCenter::currentNotificationCenter();
    let (sender, receiver) = mpsc::channel();
    let completion = RcBlock::new(move |settings: NonNull<UNNotificationSettings>| {
        // UserNotifications owns the settings object for the duration of the callback.
        let status = unsafe { settings.as_ref() }.authorizationStatus();
        let _ = sender.send(notification_permission_name(status).to_string());
    });
    center.getNotificationSettingsWithCompletionHandler(&completion);
    receiver
}

#[cfg(target_os = "macos")]
fn notification_permission_request_receiver() -> mpsc::Receiver<String> {
    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_foundation::NSError;
    use objc2_user_notifications::{UNAuthorizationOptions, UNUserNotificationCenter};

    let center = UNUserNotificationCenter::currentNotificationCenter();
    let (sender, receiver) = mpsc::channel();
    let completion = RcBlock::new(move |granted: Bool, error: *mut NSError| {
        let permission = if !error.is_null() {
            "unavailable"
        } else if granted.as_bool() {
            "granted"
        } else {
            "denied"
        };
        let _ = sender.send(permission.to_string());
    });
    center.requestAuthorizationWithOptions_completionHandler(
        UNAuthorizationOptions::Alert | UNAuthorizationOptions::Sound,
        &completion,
    );
    receiver
}

#[cfg(not(target_os = "macos"))]
fn notification_permission_name(
    status: tauri_plugin_notification::PermissionState,
) -> &'static str {
    use tauri_plugin_notification::PermissionState;

    match status {
        PermissionState::Granted => "granted",
        PermissionState::Denied => "denied",
        PermissionState::Prompt | PermissionState::PromptWithRationale => "default",
    }
}

#[tauri::command]
async fn native_notification_permission_state(app: AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        let _ = app;
        return receive_notification_callback(
            notification_permission_state_receiver(),
            "native_notification_permission_timeout",
            "native_notification_permission_task_failed",
        )
        .await;
    }

    #[cfg(not(target_os = "macos"))]
    {
        use tauri_plugin_notification::NotificationExt;
        app.notification()
            .permission_state()
            .map(|status| notification_permission_name(status).to_string())
            .map_err(|_| "native_notification_permission_unavailable".to_string())
    }
}

#[tauri::command]
async fn request_native_notification_permission(app: AppHandle) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        let _ = app;
        return receive_notification_callback(
            notification_permission_request_receiver(),
            "native_notification_permission_timeout",
            "native_notification_permission_task_failed",
        )
        .await;
    }

    #[cfg(not(target_os = "macos"))]
    {
        use tauri_plugin_notification::NotificationExt;
        app.notification()
            .request_permission()
            .map(|status| notification_permission_name(status).to_string())
            .map_err(|_| "native_notification_permission_unavailable".to_string())
    }
}

fn round_notification_is_background(focused: bool, minimized: bool, visible: bool) -> bool {
    minimized || !visible || !focused
}

#[cfg(target_os = "macos")]
fn notification_delivery_receiver(title: &str, body: &str) -> mpsc::Receiver<Result<(), String>> {
    use block2::RcBlock;
    use objc2_foundation::{NSError, NSString};
    use objc2_user_notifications::{
        UNMutableNotificationContent, UNNotificationRequest, UNNotificationSound,
        UNUserNotificationCenter,
    };

    static NEXT_NOTIFICATION_ID: std::sync::atomic::AtomicU64 =
        std::sync::atomic::AtomicU64::new(1);

    let content = UNMutableNotificationContent::new();
    content.setTitle(&NSString::from_str(title));
    content.setBody(&NSString::from_str(body));
    content.setSound(Some(&UNNotificationSound::defaultSound()));
    let identifier = NSString::from_str(&format!(
        "aqa-round-{}-{}",
        std::process::id(),
        NEXT_NOTIFICATION_ID.fetch_add(1, Ordering::Relaxed)
    ));
    let request =
        UNNotificationRequest::requestWithIdentifier_content_trigger(&identifier, &content, None);
    let center = UNUserNotificationCenter::currentNotificationCenter();
    let (sender, receiver) = mpsc::channel();
    let completion = RcBlock::new(move |error: *mut NSError| {
        let result = if error.is_null() {
            Ok(())
        } else {
            Err("native_notification_delivery_rejected".to_string())
        };
        let _ = sender.send(result);
    });
    center.addNotificationRequest_withCompletionHandler(&request, Some(&completion));
    receiver
}

#[tauri::command]
async fn deliver_round_notification(
    app: AppHandle,
    title: String,
    body: String,
) -> Result<Value, String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "native_notification_window_unavailable".to_string())?;
    let focused = window
        .is_focused()
        .map_err(|_| "native_notification_focus_unavailable".to_string())?;
    let minimized = window
        .is_minimized()
        .map_err(|_| "native_notification_minimized_unavailable".to_string())?;
    let visible = window
        .is_visible()
        .map_err(|_| "native_notification_visibility_unavailable".to_string())?;

    if !round_notification_is_background(focused, minimized, visible) {
        return Ok(serde_json::json!({
            "status": "suppressed",
            "focused": focused,
            "minimized": minimized,
            "visible": visible,
        }));
    }

    #[cfg(target_os = "macos")]
    {
        receive_notification_callback(
            notification_delivery_receiver(&title, &body),
            "native_notification_delivery_timeout",
            "native_notification_delivery_task_failed",
        )
        .await??;
    }

    #[cfg(not(target_os = "macos"))]
    {
        use tauri_plugin_notification::NotificationExt;
        app.notification()
            .builder()
            .title(title)
            .body(body)
            .show()
            .map_err(|_| "native_notification_delivery_rejected".to_string())?;
    }

    Ok(serde_json::json!({
        "status": "queued",
        "focused": focused,
        "minimized": minimized,
        "visible": visible,
    }))
}

fn main() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());
    #[cfg(not(target_os = "macos"))]
    let builder = builder.plugin(tauri_plugin_notification::init());
    builder
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            reveal_main_window(app);
        }))
        .invoke_handler(tauri::generate_handler![
            save_markdown_export,
            pick_local_ai_import_directory,
            reveal_managed_path,
            set_native_menu_locale,
            set_native_appearance,
            native_notification_permission_state,
            request_native_notification_permission,
            deliver_round_notification,
            update_generation_sleep_inhibition
        ])
        .setup(|app| {
            let preferences_path = desktop_data_dir()
                .map_err(|error| -> Box<dyn std::error::Error> { error.into() })?
                .join(DESKTOP_PREFERENCES_FILE);
            app.manage(load_desktop_preferences(preferences_path));
            app.manage(SleepInhibitionManager::new());
            install_menu(&app.handle(), NativeMenuLocale::English)?;
            match start_backend(&app.handle()) {
                Ok(url) => {
                    if let Err(error) = show_window(&app.handle(), url) {
                        stop_backend(&app.handle());
                        return Err(error.into());
                    }
                    monitor_backend(app.handle().clone());
                    monitor_sleep_inhibition(app.handle().clone());
                    Ok(())
                }
                Err(error) => {
                    let log_path = desktop_data_dir()
                        .unwrap_or_else(|_| PathBuf::from("logs"))
                        .join("logs/desktop-backend.log");
                    let backend = Backend::new(log_path);
                    fail(&app.handle(), &backend, &error);
                    Err(error.into())
                }
            }
        })
        .on_menu_event(|app, event| {
            if let Some(action) = ViewMenuAction::from_menu_id(event.id().as_ref()) {
                handle_view_menu_action(app, action);
            }
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                #[cfg(target_os = "macos")]
                {
                    api.prevent_close();
                    // Hiding only the NSWindow while it owns a fullscreen Space
                    // leaves an orphan black Space. AppKit's application hide is
                    // the native Command-H path and preserves a clean Dock reopen.
                    let _ = window.app_handle().hide();
                }
                #[cfg(not(target_os = "macos"))]
                {
                    api.prevent_close();
                    stop_sleep_inhibition(&window.app_handle());
                    stop_backend(&window.app_handle());
                    window.app_handle().exit(0);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building AQA desktop shell")
        .run(|app, event| match event {
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => reveal_main_window(app),
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                stop_sleep_inhibition(app);
                stop_backend(app);
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appearance_uses_explicit_themes_and_clears_system_override() {
        assert_eq!(appearance_theme("system").unwrap(), None);
        assert_eq!(
            appearance_theme("light").unwrap(),
            Some(tauri::Theme::Light)
        );
        assert_eq!(appearance_theme("dark").unwrap(), Some(tauri::Theme::Dark));
        assert!(appearance_theme("invalid").is_err());
    }

    #[test]
    fn backend_stdout_is_drained_after_startup_receiver_closes() {
        let stdout = std::io::Cursor::new("ready\naccess one\naccess two\naccess three\n");
        let (sender, receiver) = mpsc::sync_channel(1);
        let reader = thread::spawn(move || drain_backend_stdout(stdout, sender));

        assert_eq!(receiver.recv().unwrap(), "ready");
        drop(receiver);

        assert_eq!(reader.join().unwrap(), 4);
    }

    #[test]
    fn sleep_inhibition_requires_enabled_active_work() {
        let mut state = SleepInhibitionState {
            enabled: true,
            active_operations: HashMap::new(),
            inhibitor: None,
            acquisition_failed: false,
        };
        assert!(!state.should_inhibit());

        state
            .active_operations
            .insert("round-a".to_string(), Instant::now());
        assert!(state.should_inhibit());

        state.enabled = false;
        assert!(!state.should_inhibit());
    }

    #[test]
    fn linux_inhibitor_targets_automatic_idle_handling_only() {
        assert_eq!(LINUX_SYSTEMD_INHIBIT_ARGS[0], "--what=idle");
        assert!(!LINUX_SYSTEMD_INHIBIT_ARGS.contains(&"--what=sleep"));
        assert!(LINUX_SYSTEMD_INHIBIT_ARGS.contains(&"--no-ask-password"));
        assert!(LINUX_INHIBITOR_SUPERVISOR.contains("trap cleanup TERM INT HUP EXIT"));
        assert!(LINUX_INHIBITOR_SUPERVISOR.contains("kill -TERM -- -$$"));
        assert!(linux_parent_changed(42, 1));
        assert!(!linux_parent_changed(42, 42));
    }

    #[test]
    fn macos_inhibitor_uses_idle_scope_and_tracks_the_aqa_process() {
        assert_eq!(
            macos_caffeinate_arguments(12_345),
            ["-i".to_string(), "-w".to_string(), "12345".to_string()]
        );
    }

    #[test]
    fn sleep_inhibition_leases_expire_without_affecting_fresh_operations() {
        let now = Instant::now();
        let mut state = SleepInhibitionState {
            enabled: false,
            active_operations: HashMap::from([
                ("stale".to_string(), now - SLEEP_INHIBITION_LEASE_TIMEOUT),
                (
                    "fresh".to_string(),
                    now - SLEEP_INHIBITION_LEASE_TIMEOUT + Duration::from_secs(1),
                ),
            ]),
            inhibitor: None,
            acquisition_failed: false,
        };

        state.expire_stale_operations(now);

        assert_eq!(state.active_operations.len(), 1);
        assert!(state.active_operations.contains_key("fresh"));
    }

    #[test]
    fn sleep_inhibition_heartbeat_does_not_retry_a_latched_acquisition_failure() {
        let manager = SleepInhibitionManager::new();
        {
            let mut state = manager.state.lock().unwrap();
            state.enabled = false;
            state.acquisition_failed = true;
            state
                .active_operations
                .insert("round-a".to_string(), Instant::now());
        }

        manager.update("round-a".to_string(), true, false).unwrap();
        assert!(manager.state.lock().unwrap().acquisition_failed);

        manager.update("round-b".to_string(), true, false).unwrap();
        assert!(!manager.state.lock().unwrap().acquisition_failed);
    }

    #[test]
    fn disabled_sleep_inhibition_tracks_concurrent_operations_independently() {
        let manager = SleepInhibitionManager::new();
        manager.update("round-a".to_string(), true, false).unwrap();
        manager.update("round-b".to_string(), true, false).unwrap();
        // Completion carries an intentionally stale value; it may remove its
        // own operation but must not re-enable inhibition for round-b.
        manager.update("round-a".to_string(), false, true).unwrap();

        let state = manager.state.lock().unwrap();
        assert_eq!(state.active_operations.len(), 1);
        assert!(state.active_operations.contains_key("round-b"));
        assert!(!state.enabled);
        assert!(!state.should_inhibit());
    }

    #[test]
    fn sleep_inhibition_rejects_unscoped_operation_ids() {
        let manager = SleepInhibitionManager::new();
        assert_eq!(
            manager.update("  ".to_string(), true, false),
            Err("sleep_inhibition_operation_id_invalid".to_string())
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn macos_idle_sleep_inhibitor_is_owned_and_released() {
        let mut inhibitor = PlatformSleepInhibitor::acquire().unwrap();
        assert!(inhibitor.is_active());
        inhibitor.release().unwrap();
        assert!(!inhibitor.is_active());
    }

    #[test]
    fn native_menu_locale_accepts_supported_language_tags_only() {
        assert_eq!(parse_native_menu_locale("de"), Ok(NativeMenuLocale::German));
        assert_eq!(
            parse_native_menu_locale("de-DE"),
            Ok(NativeMenuLocale::German)
        );
        assert_eq!(
            parse_native_menu_locale("en_US"),
            Ok(NativeMenuLocale::English)
        );
        assert!(parse_native_menu_locale("fr-FR").is_err());
    }

    #[test]
    fn native_menu_labels_switch_without_changing_menu_actions() {
        assert_eq!(
            native_menu_label(NativeMenuLocale::German, NativeMenuLabel::View),
            "Darstellung"
        );
        assert_eq!(
            native_menu_label(NativeMenuLocale::English, NativeMenuLabel::View),
            "View"
        );
        assert_eq!(
            native_menu_label(NativeMenuLocale::German, NativeMenuLabel::Copy),
            "Kopieren"
        );
        assert_eq!(
            native_menu_label(NativeMenuLocale::English, NativeMenuLabel::Copy),
            "Copy"
        );
        assert_eq!(
            ViewMenuAction::from_menu_id(MENU_ABOUT),
            Some(ViewMenuAction::About)
        );
        assert_eq!(
            ViewMenuAction::from_menu_id(MENU_ZOOM_IN),
            Some(ViewMenuAction::ZoomIn)
        );
    }

    #[test]
    fn maps_view_menu_ids_to_actions() {
        assert_eq!(
            ViewMenuAction::from_menu_id(MENU_ABOUT),
            Some(ViewMenuAction::About)
        );
        assert_eq!(
            ViewMenuAction::from_menu_id(MENU_RELOAD),
            Some(ViewMenuAction::Reload)
        );
        assert_eq!(
            ViewMenuAction::from_menu_id(MENU_ZOOM_IN),
            Some(ViewMenuAction::ZoomIn)
        );
        assert_eq!(ViewMenuAction::from_menu_id("other"), None);
    }

    #[test]
    fn round_notifications_use_native_background_state() {
        assert!(!round_notification_is_background(true, false, true));
        assert!(round_notification_is_background(false, false, true));
        assert!(round_notification_is_background(true, true, true));
        assert!(round_notification_is_background(false, true, true));
        assert!(round_notification_is_background(true, false, false));
    }

    #[test]
    fn zoom_steps_are_bounded_and_reset_invalid_values() {
        assert_eq!(next_zoom_factor(1.0, 1.0), 1.1);
        assert_eq!(next_zoom_factor(1.0, -1.0), 0.9);
        assert_eq!(next_zoom_factor(1.25, 1.0), 1.4);
        assert_eq!(next_zoom_factor(1.25, -1.0), 1.2);
        assert_eq!(next_zoom_factor(MAX_ZOOM_FACTOR, 1.0), MAX_ZOOM_FACTOR);
        assert_eq!(next_zoom_factor(MIN_ZOOM_FACTOR, -1.0), MIN_ZOOM_FACTOR);
        assert_eq!(next_zoom_factor(f64::NAN, 1.0), 1.1);
        assert_eq!(next_zoom_factor(f64::INFINITY, -1.0), 0.9);
    }

    #[test]
    fn invalid_or_missing_preferences_fall_back_to_actual_size() {
        assert_eq!(parse_zoom_factor(r#"{"zoom_factor":1.3}"#), 1.3);
        assert_eq!(parse_zoom_factor(r#"{"zoom_factor":4}"#), MAX_ZOOM_FACTOR);
        assert_eq!(
            parse_zoom_factor(r#"{"zoom_factor":4.1}"#),
            DEFAULT_ZOOM_FACTOR
        );
        assert_eq!(
            parse_zoom_factor(r#"{"zoom_factor":0.49}"#),
            DEFAULT_ZOOM_FACTOR
        );
        assert_eq!(
            parse_zoom_factor(r#"{"zoom_factor":"large"}"#),
            DEFAULT_ZOOM_FACTOR
        );
        assert_eq!(parse_zoom_factor(r#"{}"#), DEFAULT_ZOOM_FACTOR);
        assert_eq!(
            parse_zoom_factor(r#"{"zoom_factor":null}"#),
            DEFAULT_ZOOM_FACTOR
        );
        assert_eq!(parse_zoom_factor("not json"), DEFAULT_ZOOM_FACTOR);
    }

    #[test]
    fn explicit_desktop_data_directory_is_isolated_and_absolute() {
        let isolated = std::env::temp_dir().join("aqa-desktop-test-data");
        assert_eq!(
            desktop_data_dir_path(Some(isolated.clone())).unwrap(),
            isolated
        );
        assert!(desktop_data_dir_path(Some(PathBuf::from("relative"))).is_err());
    }

    #[test]
    fn markdown_export_filename_is_narrowly_validated() {
        assert!(valid_markdown_export_filename("discussion-2026-09-02.md"));
        assert!(valid_markdown_export_filename("diskussion-2026-09-02.md"));
        assert!(valid_markdown_export_filename(
            "2026-09-04_16-13_AQA_bauen-im-bestand.md"
        ));
        assert!(!valid_markdown_export_filename("../discussion.md"));
        assert!(!valid_markdown_export_filename("discussion.txt"));
        assert!(!valid_markdown_export_filename(".md"));
        assert!(!valid_markdown_export_filename(&format!(
            "{}.md",
            "a".repeat(121)
        )));
    }

    #[test]
    fn markdown_export_write_distinguishes_save_cancel_and_error() {
        let path = std::env::temp_dir().join(format!(
            "aqa-markdown-export-{}-success.md",
            std::process::id()
        ));
        let _ = fs::remove_file(&path);

        assert_eq!(
            write_markdown_export(Some(FilePath::Path(path.clone())), "# Export").unwrap(),
            path.file_name()
                .and_then(|value| value.to_str())
                .map(str::to_string)
        );
        assert_eq!(fs::read_to_string(&path).unwrap(), "# Export");
        fs::remove_file(&path).unwrap();

        assert_eq!(write_markdown_export(None, "# Export").unwrap(), None);

        let missing_parent = std::env::temp_dir()
            .join(format!("aqa-export-missing-{}", std::process::id()))
            .join("export.md");
        assert!(write_markdown_export(Some(FilePath::Path(missing_parent)), "# Export").is_err());
    }

    #[test]
    fn local_ai_directory_picker_distinguishes_selection_cancel_and_invalid_path() {
        let directory = std::env::temp_dir();
        assert_eq!(
            resolve_picked_directory(Some(FilePath::Path(directory.clone()))).unwrap(),
            directory.to_str().map(str::to_string)
        );
        assert_eq!(resolve_picked_directory(None).unwrap(), None);

        let missing = directory.join(format!("aqa-missing-import-{}", std::process::id()));
        assert!(resolve_picked_directory(Some(FilePath::Path(missing))).is_err());
    }

    #[test]
    fn managed_path_resolution_accepts_only_known_paths_below_the_data_root() {
        let root = std::env::temp_dir().join(format!("aqa-managed-path-{}", std::process::id()));
        let sessions = root.join("conversations");
        let models = root.join("local-ai/models");
        fs::create_dir_all(&sessions).unwrap();
        fs::create_dir_all(&models).unwrap();
        let session = sessions.join("safe-session.json");
        fs::write(&session, "{}").unwrap();

        assert_eq!(
            resolve_managed_path(&root, "session", Some("safe-session")).unwrap(),
            (session.canonicalize().unwrap(), true)
        );
        assert_eq!(
            resolve_managed_path(&root, "local_ai_models", None).unwrap(),
            (models.canonicalize().unwrap(), false)
        );
        assert!(resolve_managed_path(&root, "session", Some("../escape")).is_err());
        assert!(resolve_managed_path(&root, "unknown", None).is_err());

        fs::remove_dir_all(root).unwrap();
    }
}
