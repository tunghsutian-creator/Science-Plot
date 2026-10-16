import AppKit
import CryptoKit
import Darwin
import Foundation

private struct LauncherTestFailure: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

private struct LauncherIdentity: Codable, Equatable {
    let applicationID: String
    let sourceHead: String
    let contentHash: String
}

private struct LauncherAsset: Decodable {
    let path: String
    let bytes: Int
    let sha256: String
}

private struct LauncherManifest: Decodable {
    let build: LauncherIdentity
    let files: [LauncherAsset]
}

private struct LauncherHealth: Codable, Equatable {
    let applicationID: String
    let sourceHead: String
    let contentHash: String
    let instanceID: String
    let pid: Int32
    let port: UInt16
}

private struct LauncherState: Decodable {
    let health: LauncherHealth
    let bundlePath: String
}

private struct LauncherQASettings {
    let support: URL
    let logs: URL
    let preferredPort: UInt16
    let portCount: Int
    let noBrowser: Bool

    var environment: [String: String] {
        var result = ProcessInfo.processInfo.environment
        for key in result.keys where key.hasPrefix("QA_") || key == "FIGURE_ASSEMBLY_LAUNCHER_QA" {
            result.removeValue(forKey: key)
        }
        result["FIGURE_ASSEMBLY_LAUNCHER_QA"] = "1"
        result["QA_SUPPORT_DIR"] = support.path
        result["QA_LOG_DIR"] = logs.path
        result["QA_PREFERRED_PORT"] = String(preferredPort)
        result["QA_PORT_COUNT"] = String(portCount)
        result["QA_NO_BROWSER"] = noBrowser ? "1" : "0"
        // Runtime launch must work without discovering Node, Python or a shell
        // helper through the developer's search path. HOME is never replaced.
        result["PATH"] = "/nonexistent-figure-assembly-qa"
        return result
    }
}

@MainActor
private final class BrowserLauncherRun {
    let app: URL
    let output: URL
    let executable: URL
    let manifest: LauncherManifest
    var checks: [String] = []
    var observations: [[String: Any]] = []
    var ownedProcesses: [Process] = []
    var ownedApplications: [NSRunningApplication] = []

    init(app: URL, output: URL) throws {
        self.app = app.resolvingSymlinksInPath().standardizedFileURL
        self.output = output
        let resources = self.app.appendingPathComponent("Contents/Resources", isDirectory: true)
        manifest = try JSONDecoder().decode(LauncherManifest.self, from: Data(contentsOf: resources.appendingPathComponent("BrowserBuild.json")))
        let plist = try PropertyListSerialization.propertyList(from: Data(contentsOf: self.app.appendingPathComponent("Contents/Info.plist")), format: nil)
        guard let info = plist as? [String: Any], let binary = info["CFBundleExecutable"] as? String,
              info["CFBundleIdentifier"] as? String == "org.sciplot.figureassembly.browser",
              manifest.build.applicationID == "org.sciplot.figureassembly.browser" else {
            throw LauncherTestFailure("Expected the independent Figure Assembly Browser app and manifest identity.")
        }
        executable = self.app.appendingPathComponent("Contents/MacOS/\(binary)")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
    }

    func run() async throws {
        try verifyRuntimeBoundary()
        let portFixture = try startPortFixture(name: "initial-port-reservation")
        let initialPort = try fixturePort(portFixture)
        try stopFixture(portFixture)
        let lifecycle = try settings("lifecycle", port: initialPort, noBrowser: true)
        let first = try launchDirect(lifecycle, name: "first-launch")
        let health = try await waitForHealth(lifecycle, expectedPID: first.processIdentifier)
        try await verifyServing(health)
        let status = try control("--status", settings: lifecycle)
        guard status.status == 0, let statusBytes = status.output.data(using: .utf8),
              try JSONDecoder().decode(LauncherState.self, from: statusBytes).health == health else {
            throw LauncherTestFailure("The read-only status command did not report the actual healthy owner.")
        }
        try verifyStopIdentityRefusal(lifecycle, health: health)
        let listeners = try command("/usr/sbin/lsof", ["-nP", "-a", "-p", String(health.pid), "-iTCP", "-sTCP:LISTEN"])
        guard listeners.status == 0, listeners.output.contains("127.0.0.1:\(health.port)"),
              !listeners.output.contains("TCP *:"), !listeners.output.contains("0.0.0.0:"),
              !listeners.output.contains("[::]:") else {
            throw LauncherTestFailure("The launcher listener must be IPv4 loopback only: \(listeners.output)")
        }
        try Data(listeners.output.utf8).write(to: output.appendingPathComponent("listener.txt"))
        checks.append("Actual packaged Mach-O launches with no usable executable search path; health has exact build identity, live app PID and loopback-only listener; bundled index bytes/hash match HTTP.")

        let second = try launchDirect(lifecycle, name: "duplicate-launch")
        try await waitForExit(second)
        guard second.terminationStatus == 0 else { throw LauncherTestFailure("Duplicate launcher failed instead of reusing its healthy owner.") }
        let reused = try await fetchHealth(port: health.port)
        guard reused == health else { throw LauncherTestFailure("A duplicate launch changed the owned server PID, port or instance ID.") }
        try await waitForLog("reused", settings: lifecycle)
        observations.append(["phase": "direct-reuse", "health": try json(health), "duplicatePID": second.processIdentifier])
        checks.append("A second actual Mach-O invocation exits successfully and reuses the same healthy PID, port, instance and build; no duplicate server.")

        try await quitNormally(health)
        try await waitForClosed(port: health.port)
        let restarted = try launchDirect(lifecycle, name: "restart-after-quit")
        let restartedHealth = try await waitForHealth(lifecycle, expectedPID: restarted.processIdentifier)
        guard restartedHealth.instanceID != health.instanceID else { throw LauncherTestFailure("Restart retained a stopped server's instance ID.") }
        observations.append(["phase": "restart", "before": try json(health), "after": try json(restartedHealth)])
        let stopped = try control("--stop", settings: lifecycle)
        guard stopped.status == 0, stopped.output.contains("stopped") else { throw LauncherTestFailure("The identity-checked stop command failed to quit its owned app normally.") }
        try await waitForClosed(port: restartedHealth.port)
        checks.append("Normal AppKit termination stops the owned listener; relaunch creates a fresh live instance, then identity-checked --stop closes it cleanly. A wrong bundle identity is refused without stopping the healthy app.")

        let conflict = try startPortFixture(name: "unrelated-port-owner")
        let blockedPort = try fixturePort(conflict)
        let conflicting = try settings("conflict", port: blockedPort, noBrowser: true)
        let conflictLaunch = try launchDirect(conflicting, name: "conflict-launch")
        let conflictHealth = try await waitForHealth(conflicting, expectedPID: conflictLaunch.processIdentifier)
        guard conflictHealth.port > blockedPort, Int(conflictHealth.port) < Int(blockedPort) + conflicting.portCount,
              conflict.isRunning, Darwin.kill(conflict.processIdentifier, 0) == 0 else {
            throw LauncherTestFailure("Occupied preferred port did not cause a bounded fallback preserving the unrelated owner.")
        }
        observations.append(["phase": "port-conflict", "preferredPort": blockedPort, "fixturePID": conflict.processIdentifier, "health": try json(conflictHealth)])
        try await quitNormally(conflictHealth)
        try await waitForClosed(port: conflictHealth.port)
        guard conflict.isRunning else { throw LauncherTestFailure("Quitting the app stopped the unrelated preferred-port owner.") }
        try stopFixture(conflict)
        checks.append("An independent owned fixture occupies the preferred port; the launcher selects a later allowed port without killing that process, including on quit.")

        let edge = try settings("launch-services-edge", port: initialPort, noBrowser: false)
        let priorPIDs = Set(NSRunningApplication.runningApplications(withBundleIdentifier: manifest.build.applicationID).map(\.processIdentifier))
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.createsNewApplicationInstance = true
        configuration.environment = edge.environment
        let launched = try await NSWorkspace.shared.openApplication(at: app, configuration: configuration)
        guard !priorPIDs.contains(launched.processIdentifier), launched.bundleURL?.resolvingSymlinksInPath().standardizedFileURL == app else {
            throw LauncherTestFailure("LaunchServices did not return a new QA-owned instance; no preexisting app will be terminated.")
        }
        ownedApplications.append(launched)
        let edgeHealth = try await waitForHealth(edge, expectedPID: launched.processIdentifier)
        let firstEvents = try await waitForEdgeLog(settings: edge, health: edgeHealth, minimumCount: 1)
        let reopen = NSWorkspace.OpenConfiguration()
        reopen.activates = false
        reopen.createsNewApplicationInstance = false
        reopen.environment = edge.environment
        let reopened = try await NSWorkspace.shared.openApplication(at: app, configuration: reopen)
        guard reopened.processIdentifier == launched.processIdentifier else {
            throw LauncherTestFailure("The normal LaunchServices reopen did not reuse this QA app PID.")
        }
        _ = try await waitForEdgeLog(settings: edge, health: edgeHealth, minimumCount: firstEvents + 1)
        guard try await fetchHealth(port: edgeHealth.port) == edgeHealth else { throw LauncherTestFailure("Reopen replaced its healthy server.") }
        observations.append(["phase": "launch-services-reopen", "health": try json(edgeHealth), "returnedPID": reopened.processIdentifier])
        try await quitNormally(edgeHealth)
        try await waitForClosed(port: edgeHealth.port)
        checks.append("Actual LaunchServices .app open and normal second reopen reuse the same healthy owner; each real NSWorkspace Edge completion reports com.microsoft.edgemac and the correct loopback URL. No Edge tabs were read or closed.")
        try writeReport(status: "PASS")
    }

    func settings(_ name: String, port: UInt16, noBrowser: Bool) throws -> LauncherQASettings {
        let root = output.appendingPathComponent(name, isDirectory: true)
        let support = root.appendingPathComponent("support", isDirectory: true)
        let logs = root.appendingPathComponent("logs", isDirectory: true)
        guard !FileManager.default.fileExists(atPath: root.path) else { throw LauncherTestFailure("Use a fresh evidence directory; QA support state already exists: \(name)") }
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        return LauncherQASettings(support: support, logs: logs, preferredPort: port, portCount: 8, noBrowser: noBrowser)
    }

    func launchDirect(_ settings: LauncherQASettings, name: String) throws -> Process {
        let process = Process()
        process.executableURL = executable
        process.environment = settings.environment
        process.standardInput = FileHandle.nullDevice
        let standardOutput = output.appendingPathComponent("\(name).stdout.log")
        let standardError = output.appendingPathComponent("\(name).stderr.log")
        _ = FileManager.default.createFile(atPath: standardOutput.path, contents: nil)
        _ = FileManager.default.createFile(atPath: standardError.path, contents: nil)
        process.standardOutput = try FileHandle(forWritingTo: standardOutput)
        process.standardError = try FileHandle(forWritingTo: standardError)
        try process.run()
        ownedProcesses.append(process)
        return process
    }

    func waitForHealth(_ settings: LauncherQASettings, expectedPID: Int32) async throws -> LauncherHealth {
        let stateFile = settings.support.appendingPathComponent("server-state.json")
        for _ in 0..<150 {
            if let bytes = try? Data(contentsOf: stateFile), let state = try? JSONDecoder().decode(LauncherState.self, from: bytes),
               let health = try? await fetchHealth(port: state.health.port), health == state.health,
               health.pid == expectedPID {
                guard health.applicationID == manifest.build.applicationID, health.sourceHead == manifest.build.sourceHead,
                      health.contentHash == manifest.build.contentHash, !health.instanceID.isEmpty,
                      Darwin.kill(health.pid, 0) == 0,
                      URL(fileURLWithPath: state.bundlePath).resolvingSymlinksInPath().standardizedFileURL == app else {
                    throw LauncherTestFailure("Health/state identity does not match the real QA app, build and live PID.")
                }
                return health
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("No matching live QA-owned health within 15 seconds: PID \(expectedPID).")
    }

    func fetchHealth(port: UInt16) async throws -> LauncherHealth {
        let (bytes, response) = try await request(port: port, path: "/__figure_assembly_health")
        guard response.statusCode == 200 else { throw LauncherTestFailure("Health status \(response.statusCode)") }
        return try JSONDecoder().decode(LauncherHealth.self, from: bytes)
    }

    func request(port: UInt16, path: String) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
        request.timeoutInterval = 2
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        let (bytes, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw LauncherTestFailure("Non-HTTP loopback response.") }
        return (bytes, response)
    }

    func verifyServing(_ health: LauncherHealth) async throws {
        guard let index = manifest.files.first(where: { $0.path == "index.html" }) else { throw LauncherTestFailure("Bundled index.html is absent from the allowlist manifest.") }
        let (bytes, response) = try await request(port: health.port, path: "/")
        guard response.statusCode == 200, bytes.count == index.bytes, digest(bytes) == index.sha256,
              String(data: bytes, encoding: .utf8)?.contains("Figure Assembly") == true else {
            throw LauncherTestFailure("HTTP root does not serve the exact bundled index bytes.")
        }
        try bytes.write(to: output.appendingPathComponent("served-index.html"))
    }

    func waitForExit(_ process: Process) async throws {
        for _ in 0..<80 {
            if !process.isRunning { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("Owned process \(process.processIdentifier) did not exit within 8 seconds.")
    }

    func control(_ action: String, settings: LauncherQASettings) throws -> (status: Int32, output: String) {
        let task = Process(), output = Pipe(), errors = Pipe()
        task.executableURL = executable
        task.arguments = [action]
        task.environment = settings.environment
        task.standardOutput = output
        task.standardError = errors
        try task.run()
        let bytes = output.fileHandleForReading.readDataToEndOfFile()
        let errorBytes = errors.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        try errorBytes.write(to: self.output.appendingPathComponent("control-\(action.dropFirst(2))-\(UUID().uuidString).stderr.log"))
        return (task.terminationStatus, String(decoding: bytes, as: UTF8.self))
    }

    func verifyStopIdentityRefusal(_ settings: LauncherQASettings, health: LauncherHealth) throws {
        let stateFile = settings.support.appendingPathComponent("server-state.json")
        let original = try Data(contentsOf: stateFile)
        defer { try? original.write(to: stateFile, options: [.atomic]) }
        guard var wrong = try JSONSerialization.jsonObject(with: original) as? [String: Any] else { throw LauncherTestFailure("QA state is not an object.") }
        wrong["bundlePath"] = output.appendingPathComponent("Different Application.app").path
        try JSONSerialization.data(withJSONObject: wrong).write(to: stateFile, options: [.atomic])
        let refused = try control("--stop", settings: settings)
        guard refused.status == 4, Darwin.kill(health.pid, 0) == 0 else {
            throw LauncherTestFailure("A stop request with the wrong app bundle identity was not refused safely.")
        }
    }

    func waitForClosed(port: UInt16) async throws {
        for _ in 0..<50 {
            if (try? await fetchHealth(port: port)) == nil { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("Owned health endpoint still answers after normal Quit.")
    }

    func quitNormally(_ health: LauncherHealth) async throws {
        guard let application = NSRunningApplication(processIdentifier: health.pid),
              application.bundleURL?.resolvingSymlinksInPath().standardizedFileURL == app,
              ownedProcesses.contains(where: { $0.processIdentifier == health.pid }) || ownedApplications.contains(where: { $0.processIdentifier == health.pid }) else {
            throw LauncherTestFailure("Refusing to terminate a PID not owned by this test and app bundle.")
        }
        guard application.terminate() else { throw LauncherTestFailure("QA-owned app refused normal AppKit Quit.") }
        for _ in 0..<80 {
            if application.isTerminated { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("Normal AppKit Quit did not terminate the QA-owned app.")
    }

    func logEntries(_ settings: LauncherQASettings) throws -> [[String: Any]] {
        let file = settings.logs.appendingPathComponent("launcher.jsonl")
        guard let text = try? String(contentsOf: file, encoding: .utf8) else { return [] }
        return try text.split(separator: "\n").map { line in
            guard let entry = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { throw LauncherTestFailure("Invalid JSONL launcher log entry.") }
            return entry
        }
    }

    func waitForLog(_ event: String, settings: LauncherQASettings) async throws {
        for _ in 0..<80 {
            if try logEntries(settings).contains(where: { $0["event"] as? String == event }) { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("Missing launcher event: \(event).")
    }

    func waitForEdgeLog(settings: LauncherQASettings, health: LauncherHealth, minimumCount: Int) async throws -> Int {
        for _ in 0..<150 {
            let entries = try logEntries(settings).filter { $0["event"] as? String == "edge_opened" }
            if entries.count >= minimumCount {
                for entry in entries {
                    let success = entry["success"] as? Bool == true || entry["success"] as? String == "true"
                    guard success, entry["bundleIdentifier"] as? String == "com.microsoft.edgemac",
                          let text = entry["url"] as? String, let url = URL(string: text),
                          url.scheme == "http", url.host == "127.0.0.1", url.port == Int(health.port),
                          let edgePID = Int32(String(describing: entry["edgePid"] ?? "")), edgePID > 0,
                          NSRunningApplication(processIdentifier: edgePID)?.bundleIdentifier == "com.microsoft.edgemac" else {
                        throw LauncherTestFailure("Actual NSWorkspace Edge completion did not bind the expected browser and healthy URL.")
                    }
                }
                return entries.count
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw LauncherTestFailure("Missing actual Edge-open completion after app open/reopen.")
    }

    func verifyRuntimeBoundary() throws {
        let dependencies = try command("/usr/bin/otool", ["-L", executable.path])
        guard dependencies.status == 0 else { throw LauncherTestFailure("Could not inspect packaged Mach-O dependencies.") }
        let lines = dependencies.output.split(separator: "\n").dropFirst()
        guard !lines.isEmpty, lines.allSatisfy({ line in
            let path = line.trimmingCharacters(in: .whitespaces).split(separator: " ").first.map(String.init) ?? ""
            return path.hasPrefix("/System/Library/") || path.hasPrefix("/usr/lib/")
        }), !dependencies.output.lowercased().contains("python"), !dependencies.output.lowercased().contains("node") else {
            throw LauncherTestFailure("Browser launcher links a non-system runtime dependency.")
        }
        try Data(dependencies.output.utf8).write(to: output.appendingPathComponent("linked-libraries.txt"))
    }

    func command(_ executable: String, _ arguments: [String]) throws -> (status: Int32, output: String) {
        let task = Process(), output = Pipe()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        task.standardOutput = output
        task.standardError = output
        try task.run()
        let bytes = output.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        return (task.terminationStatus, String(decoding: bytes, as: UTF8.self))
    }

    func startPortFixture(name: String) throws -> Process {
        let task = Process(), input = Pipe(), output = Pipe()
        task.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        task.arguments = ["--hold-port"]
        task.standardInput = input
        task.standardOutput = output
        task.standardError = FileHandle.nullDevice
        try task.run()
        ownedProcesses.append(task)
        var line = Data()
        while !line.contains(10) {
            let byte = output.fileHandleForReading.readData(ofLength: 1)
            guard !byte.isEmpty else { throw LauncherTestFailure("Port fixture exited without binding.") }
            line.append(byte)
        }
        let receipt = outputRoot.appendingPathComponent("\(name).json")
        try line.write(to: receipt)
        fixtureInputs[task.processIdentifier] = input
        fixtureReceipts[task.processIdentifier] = line
        return task
    }

    private var outputRoot: URL { output }
    private var fixtureInputs: [Int32: Pipe] = [:]
    private var fixtureReceipts: [Int32: Data] = [:]

    func fixturePort(_ task: Process) throws -> UInt16 {
        guard let bytes = fixtureReceipts[task.processIdentifier],
              let receipt = try JSONSerialization.jsonObject(with: bytes) as? [String: Int],
              receipt["pid"] == Int(task.processIdentifier), let value = receipt["port"],
              let port = UInt16(exactly: value), port < 65520 else { throw LauncherTestFailure("Invalid owned port fixture receipt.") }
        return port
    }

    func stopFixture(_ task: Process) throws {
        try fixtureInputs.removeValue(forKey: task.processIdentifier)?.fileHandleForWriting.close()
        task.waitUntilExit()
        guard task.terminationStatus == 0 else { throw LauncherTestFailure("Owned port fixture did not close normally.") }
    }

    func cleanup() async {
        for application in ownedApplications where !application.isTerminated { _ = application.terminate() }
        for task in ownedProcesses where task.isRunning {
            if let input = fixtureInputs.removeValue(forKey: task.processIdentifier) { try? input.fileHandleForWriting.close() }
            else { task.terminate() }
        }
        try? await Task.sleep(for: .milliseconds(300))
    }

    func writeReport(status: String, error: String? = nil) throws {
        var report: [String: Any] = ["status": status, "app": app.path, "build": try json(manifest.build),
            "binarySHA256": digest(try Data(contentsOf: executable)), "checks": checks, "observations": observations,
            "scope": "Actual packaged macOS launcher, isolated QA support/logs and owned random ports; no user's server is stopped and no Edge tab is read or closed. Build tools are development-only."]
        if let error { report["error"] = error }
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: output.appendingPathComponent("browser-launcher-report.json"))
    }

    func json<T: Encodable>(_ value: T) throws -> Any { try JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) }
    func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
}

private func holdPortFixture() throws {
    var descriptor: Int32 = -1
    var selected: UInt16 = 0
    for _ in 0..<20 {
        let candidate = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard candidate >= 0 else { throw LauncherTestFailure("Fixture socket allocation failed.") }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(candidate, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard result == 0, Darwin.listen(candidate, 4) == 0 else { Darwin.close(candidate); continue }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let named = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.getsockname(candidate, $0, &length) }
        }
        let port = UInt16(bigEndian: address.sin_port)
        if named == 0 && port < 65520 { descriptor = candidate; selected = port; break }
        Darwin.close(candidate)
    }
    guard descriptor >= 0 else { throw LauncherTestFailure("No bounded random fixture port available.") }
    defer { Darwin.close(descriptor) }
    let receipt = try JSONSerialization.data(withJSONObject: ["pid": Int(getpid()), "port": Int(selected)])
    FileHandle.standardOutput.write(receipt + Data([10]))
    _ = FileHandle.standardInput.readDataToEndOfFile()
}

@main
private struct BrowserLauncherTests {
    @MainActor static func main() async throws {
        if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--hold-port" { try holdPortFixture(); return }
        guard CommandLine.arguments.count == 3 else { throw LauncherTestFailure("Usage: browser-launcher-tests APP FRESH_EVIDENCE_DIRECTORY") }
        let run = try BrowserLauncherRun(app: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true),
                                         output: URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true))
        do {
            try await run.run()
            await run.cleanup()
            print("PASS packaged browser launcher: \(run.checks.count) integration groups")
        } catch {
            await run.cleanup()
            try? run.writeReport(status: "FAIL", error: String(describing: error))
            throw error
        }
    }
}
