import AppKit
import CryptoKit
import Darwin
import Foundation
import Network

struct WebFile: Codable, Sendable {
    let path: String
    let bytes: Int
    let sha256: String
}

struct WebManifest: Codable, Sendable {
    let build: BrowserBuild
    let files: [WebFile]
}

struct ServerState: Codable, Sendable {
    let health: BrowserHealth
    let bundlePath: String
}

struct LauncherFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class LauncherLog: @unchecked Sendable {
    let url: URL
    private let handle: FileHandle
    private let lock = NSLock()

    init(directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        url = directory.appendingPathComponent("launcher.jsonl")
        let descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw LauncherFailure(message: "无法打开启动日志：\(url.path)") }
        handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    }

    func record(_ event: String, _ fields: [String: String] = [:]) {
        lock.lock(); defer { lock.unlock() }
        var values: [String: Any] = fields
        values["event"] = event
        values["timestamp"] = ISO8601DateFormatter().string(from: Date())
        values["pid"] = getpid()
        do {
            var data = try JSONSerialization.data(withJSONObject: values, options: [.sortedKeys])
            data.append(0x0a)
            try handle.write(contentsOf: data)
        } catch { NSLog("Figure Assembly Browser log: %@", error.localizedDescription) }
    }
}

struct LauncherContext: Sendable {
    let bundleURL: URL
    let webRoot: URL
    let manifest: WebManifest
    let support: URL
    let log: LauncherLog
    let preferredPort: UInt16
    let portCount: Int
    let noBrowser: Bool
    var stateURL: URL { support.appendingPathComponent("server-state.json") }
    var lockURL: URL { support.appendingPathComponent("launcher.lock") }

    init(bundle: Bundle = .main) throws {
        guard let resources = bundle.resourceURL else { throw LauncherFailure(message: "应用资源目录缺失，请重新安装完整的 .app。") }
        bundleURL = bundle.bundleURL.resolvingSymlinksInPath()
        webRoot = resources.appendingPathComponent("web", isDirectory: true)
        manifest = try JSONDecoder().decode(WebManifest.self, from: Data(contentsOf: resources.appendingPathComponent("BrowserBuild.json")))
        guard manifest.build.applicationID == "org.sciplot.figureassembly.browser", !manifest.files.isEmpty else {
            throw LauncherFailure(message: "应用构建清单无效。")
        }
        var identities: [String] = []
        var seen = Set<String>()
        for item in manifest.files.sorted(by: { $0.path < $1.path }) {
            let components = item.path.split(separator: "/", omittingEmptySubsequences: false)
            guard !item.path.hasPrefix("/"), !components.contains(".."), !components.contains("."),
                  !components.contains(""), seen.insert(item.path).inserted else {
                throw LauncherFailure(message: "应用资源路径无效。")
            }
            let candidate = webRoot.appendingPathComponent(item.path).resolvingSymlinksInPath()
            guard candidate.path.hasPrefix(webRoot.resolvingSymlinksInPath().path + "/") else {
                throw LauncherFailure(message: "应用资源越界。")
            }
            let bytes = try Data(contentsOf: candidate)
            let hash = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
            guard bytes.count == item.bytes, hash == item.sha256 else {
                throw LauncherFailure(message: "应用文件已损坏或改变：\(item.path)。请重新安装完整应用。")
            }
            identities.append("\(item.path)\t\(hash)\n")
        }
        let identity = SHA256.hash(data: Data(identities.joined().utf8)).map { String(format: "%02x", $0) }.joined()
        guard identity == manifest.build.contentHash else { throw LauncherFailure(message: "应用资源身份不匹配。") }
        let environment = ProcessInfo.processInfo.environment
        let qa = environment["FIGURE_ASSEMBLY_LAUNCHER_QA"] == "1"
        let home = FileManager.default.homeDirectoryForCurrentUser
        support = qa && environment["QA_SUPPORT_DIR"] != nil
            ? URL(fileURLWithPath: environment["QA_SUPPORT_DIR"]!, isDirectory: true)
            : home.appendingPathComponent("Library/Application Support/Figure Assembly Browser/\(identity.prefix(12))", isDirectory: true)
        let logs = qa && environment["QA_LOG_DIR"] != nil
            ? URL(fileURLWithPath: environment["QA_LOG_DIR"]!, isDirectory: true)
            : home.appendingPathComponent("Library/Logs/Figure Assembly Browser", isDirectory: true)
        preferredPort = qa ? UInt16(environment["QA_PREFERRED_PORT"] ?? "5178") ?? 5178 : 5178
        portCount = qa ? min(20, max(1, Int(environment["QA_PORT_COUNT"] ?? "20") ?? 20)) : 20
        noBrowser = qa && environment["QA_NO_BROWSER"] == "1"
        guard preferredPort > 0, Int(preferredPort) + portCount - 1 <= 65535 else { throw LauncherFailure(message: "本机端口范围无效。") }
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        log = try LauncherLog(directory: logs)
    }

    func matches(_ health: BrowserHealth) -> Bool {
        health.applicationID == manifest.build.applicationID && health.sourceHead == manifest.build.sourceHead && health.contentHash == manifest.build.contentHash
    }

    func readState() -> ServerState? {
        guard let data = try? Data(contentsOf: stateURL), let state = try? JSONDecoder().decode(ServerState.self, from: data),
              matches(state.health) else { return nil }
        return state
    }
}

private final class HealthBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: BrowserHealth?
    func set(_ health: BrowserHealth?) { lock.lock(); value = health; lock.unlock() }
    func get() -> BrowserHealth? { lock.lock(); defer { lock.unlock() }; return value }
}

func synchronousHealth(port: UInt16, timeout: TimeInterval = 1) -> BrowserHealth? {
    let semaphore = DispatchSemaphore(value: 0)
    let result = HealthBox()
    LocalWebServer.probeBrowserHealth(port: port, timeout: timeout) { health in result.set(health); semaphore.signal() }
    guard semaphore.wait(timeout: .now() + timeout + 0.5) == .success else { return nil }
    return result.get()
}

@MainActor
func runControlCommand(_ command: String, context: LauncherContext) -> Int32 {
    guard let state = context.readState(), let actual = synchronousHealth(port: state.health.port),
          actual.instanceID == state.health.instanceID, actual.pid == state.health.pid, context.matches(actual) else {
        print("{\"status\":\"not_running\"}")
        return command == "--stop" ? 0 : 3
    }
    if command == "--status" {
        if let data = try? JSONEncoder().encode(state), let value = String(data: data, encoding: .utf8) { print(value) }
        return 0
    }
    guard state.bundlePath == context.bundleURL.path,
          let app = NSRunningApplication(processIdentifier: actual.pid),
          app.bundleURL?.resolvingSymlinksInPath() == context.bundleURL,
          app.bundleIdentifier == context.manifest.build.applicationID else {
        fputs("Refusing to stop a process whose application identity differs.\n", stderr)
        return 4
    }
    guard app.terminate() else { fputs("The application did not accept a normal Quit request.\n", stderr); return 4 }
    for _ in 0..<50 {
        if synchronousHealth(port: actual.port, timeout: 0.1) == nil { print("{\"status\":\"stopped\"}"); return 0 }
        Thread.sleep(forTimeInterval: 0.1)
    }
    fputs("Normal Quit is still pending; no process was force-killed.\n", stderr)
    return 4
}

@MainActor
final class BrowserLauncher: NSObject, NSApplicationDelegate {
    let context: LauncherContext
    private let instanceID = UUID().uuidString
    private var lockDescriptor: Int32 = -1
    private var server: LocalWebServer?
    private var health: BrowserHealth?
    private var statusItem: NSStatusItem?
    private var signalSource: DispatchSourceSignal?
    private var starting = false
    private var cleaned = false
    private var operation = UUID()
    private var startupDeadline = Date()

    init(context: LauncherContext) { self.context = context }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenus()
        signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { [weak self] in self?.requestQuit() }
        source.resume(); signalSource = source
        context.log.record("starting", ["sourceHead": context.manifest.build.sourceHead, "bundlePath": context.bundleURL.path])
        ensureHealthyAndOpen()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        ensureHealthyAndOpen(); return false
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { cleanup(); return .terminateNow }
    func applicationWillTerminate(_ notification: Notification) { cleanup() }

    private func installMenus() {
        let menu = NSMenu()
        let root = NSMenuItem(title: "Figure Assembly Browser", action: nil, keyEquivalent: "")
        let actions = NSMenu(title: "Figure Assembly Browser")
        for (title, selector, shortcut) in [("打开工作台", #selector(openWorkbench), "o"), ("查看启动日志", #selector(showLogs), "l"), ("停止服务并退出", #selector(requestQuit), "q")] {
            let item = NSMenuItem(title: title, action: selector, keyEquivalent: shortcut); item.target = self; actions.addItem(item)
        }
        root.submenu = actions; menu.addItem(root); NSApplication.shared.mainMenu = menu
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.title = "FA"
        statusItem?.button?.toolTip = "Figure Assembly Browser"
        statusItem?.menu = actions.copy() as? NSMenu
    }

    @objc private func openWorkbench() { ensureHealthyAndOpen() }
    @objc private func showLogs() { NSWorkspace.shared.activateFileViewerSelecting([context.log.url]) }
    @objc private func requestQuit() { NSApplication.shared.terminate(nil) }

    private func ensureHealthyAndOpen() {
        guard !starting else { return }
        starting = true; operation = UUID(); startupDeadline = Date().addingTimeInterval(15)
        let token = operation
        if let current = health {
            LocalWebServer.probeBrowserHealth(port: current.port, timeout: 1) { [weak self] actual in
                Task { @MainActor in
                    guard let self, self.operation == token else { return }
                    if let actual, actual.instanceID == current.instanceID, self.context.matches(actual) {
                        self.starting = false; self.context.log.record("reused", ["port": String(actual.port), "instanceID": actual.instanceID])
                        self.openBrowser(actual)
                    } else { self.server?.stop(); self.server = nil; self.health = nil; self.tryPort(offset: 0, token: token) }
                }
            }
            return
        }
        lockDescriptor = Darwin.open(context.lockURL.path, O_RDWR | O_CREAT | O_NOFOLLOW, 0o600)
        guard lockDescriptor >= 0 else { fail("无法创建启动锁。", token: token); return }
        if flock(lockDescriptor, LOCK_EX | LOCK_NB) != 0 {
            close(lockDescriptor); lockDescriptor = -1
            waitForOwner(token: token)
        } else { tryPort(offset: 0, token: token) }
    }

    private func waitForOwner(token: UUID) {
        guard operation == token else { return }
        guard Date() < startupDeadline else { fail("已存在的启动器未能完成健康检查。请查看日志，或从其 Dock/菜单正常退出后再次打开。", token: token); return }
        if let state = context.readState() {
            LocalWebServer.probeBrowserHealth(port: state.health.port, timeout: 0.35) { [weak self] actual in
                Task { @MainActor in
                    guard let self, self.operation == token else { return }
                    if let actual, actual.instanceID == state.health.instanceID, self.context.matches(actual) {
                        self.starting = false; self.context.log.record("reused", ["port": String(actual.port), "instanceID": actual.instanceID, "ownerPid": String(actual.pid)])
                        self.openBrowser(actual, terminateAfterOpen: true)
                    } else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.waitForOwner(token: token) } }
                }
            }
        } else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.waitForOwner(token: token) } }
    }

    private func tryPort(offset: Int, token: UUID) {
        guard operation == token else { return }
        guard offset < context.portCount, Date() < startupDeadline else {
            fail("本机端口 \(context.preferredPort)–\(Int(context.preferredPort) + context.portCount - 1) 无法使用；没有结束任何其他进程。请查看日志。", token: token); return
        }
        let port = context.preferredPort + UInt16(offset)
        LocalWebServer.probeBrowserHealth(port: port, timeout: 0.3) { [weak self] existing in
            Task { @MainActor in
                guard let self, self.operation == token else { return }
                if let existing, self.context.matches(existing) {
                    self.starting = false; self.context.log.record("reused", ["port": String(port), "instanceID": existing.instanceID, "ownerPid": String(existing.pid)])
                    self.openBrowser(existing, terminateAfterOpen: true); return
                }
                self.bind(port: port, offset: offset, token: token)
            }
        }
    }

    private func bind(port: UInt16, offset: Int, token: UUID) {
        let log = context.log
        let candidate = LocalWebServer(root: context.webRoot, build: context.manifest.build, instanceID: instanceID, port: port,
                                       allowedFiles: Set(context.manifest.files.map(\.path)), logger: { log.record("server", ["message": $0]) })
        server = candidate
        candidate.start { [weak self] result in
            Task { @MainActor in
                guard let self, self.operation == token else { return }
                switch result {
                case .failure(let error):
                    candidate.stop(); self.server = nil
                    if let networkError = error as? NWError, case .posix(.EADDRINUSE) = networkError {
                        self.context.log.record("port_conflict", ["port": String(port)]); self.tryPort(offset: offset + 1, token: token)
                    } else { self.fail("本机服务启动失败：\(error.localizedDescription)", token: token) }
                case .success(let ready):
                    self.context.log.record("listening", ["port": String(ready.port), "instanceID": ready.instanceID])
                    LocalWebServer.probeBrowserHealth(port: port, timeout: 2) { [weak self] actual in
                        Task { @MainActor in
                            guard let self, self.operation == token else { return }
                            guard let actual, actual.instanceID == self.instanceID, actual.pid == getpid(), self.context.matches(actual) else {
                                self.fail("本机服务未通过启动健康检查。", token: token); return
                            }
                            do {
                                let state = ServerState(health: actual, bundlePath: self.context.bundleURL.path)
                                let data = try JSONEncoder().encode(state)
                                try data.write(to: self.context.stateURL, options: [.atomic])
                                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: self.context.stateURL.path)
                                self.health = actual; self.starting = false
                                self.statusItem?.button?.toolTip = "Figure Assembly Browser — 127.0.0.1:\(actual.port)"
                                self.context.log.record("health_ready", ["port": String(actual.port), "instanceID": actual.instanceID, "sourceHead": actual.sourceHead])
                                self.openBrowser(actual)
                            } catch { self.fail("无法保存本机服务状态：\(error.localizedDescription)", token: token) }
                        }
                    }
                }
            }
        }
    }

    private func openBrowser(_ actual: BrowserHealth, terminateAfterOpen: Bool = false) {
        if context.noBrowser {
            context.log.record("browser_open_skipped", ["reason": "explicit QA-only configuration"])
            if terminateAfterOpen { requestQuit() }
            return
        }
        guard let url = URL(string: "http://127.0.0.1:\(actual.port)/"),
              let edge = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.microsoft.edgemac") else {
            fail("未找到 Microsoft Edge。请安装或恢复 Edge 后再次打开；本机服务可以从菜单正常退出。", token: operation); return
        }
        let configuration = NSWorkspace.OpenConfiguration(); configuration.activates = true
        NSWorkspace.shared.open([url], withApplicationAt: edge, configuration: configuration) { [weak self] app, error in
            Task { @MainActor in
                guard let self else { return }
                let success = error == nil && app?.bundleIdentifier == "com.microsoft.edgemac"
                self.context.log.record("edge_opened", ["success": String(success), "bundleIdentifier": app?.bundleIdentifier ?? "", "edgePid": String(app?.processIdentifier ?? 0), "url": url.absoluteString, "message": error?.localizedDescription ?? ""])
                if !success { self.fail("无法打开 Microsoft Edge：\(error?.localizedDescription ?? "未返回正确的应用身份")", token: self.operation) }
                else if terminateAfterOpen { self.requestQuit() }
            }
        }
    }

    private func fail(_ message: String, token: UUID) {
        guard operation == token else { return }
        operation = UUID(); starting = false
        context.log.record("error", ["message": message])
        let alert = NSAlert(); alert.messageText = "无法启动 Figure Assembly Browser"
        alert.informativeText = message + "\n\n日志：" + context.log.url.path
        alert.addButton(withTitle: "查看日志"); alert.addButton(withTitle: "退出")
        NSApplication.shared.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertFirstButtonReturn { showLogs() }
        requestQuit()
    }

    private func cleanup() {
        guard !cleaned else { return }; cleaned = true
        operation = UUID(); context.log.record("stopping", ["instanceID": instanceID])
        server?.stop(); server = nil
        if let state = context.readState(), state.health.instanceID == instanceID { try? FileManager.default.removeItem(at: context.stateURL) }
        if lockDescriptor >= 0 { flock(lockDescriptor, LOCK_UN); close(lockDescriptor); lockDescriptor = -1 }
        signalSource?.cancel(); signalSource = nil
        if let item = statusItem { NSStatusBar.system.removeStatusItem(item) }; statusItem = nil
        context.log.record("stopped", ["instanceID": instanceID])
    }
}
