import AppKit
import CryptoKit
import Foundation

@main
struct NativeLaunchTest {
    @MainActor static func main() async throws {
        guard CommandLine.arguments.count == 3 else { throw NativeFailure("test_arguments", "native-launch APP REPORT") }
        let appURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let reportURL = URL(fileURLWithPath: CommandLine.arguments[2])
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true; configuration.createsNewApplicationInstance = true
        let running = try await NSWorkspace.shared.openApplication(at: appURL, configuration: configuration)
        for _ in 0..<30 {
            if running.isFinishedLaunching { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        try await Task.sleep(for: .seconds(2))
        guard running.isFinishedLaunching, !running.isTerminated else {
            throw NativeFailure("launch_failed", "The packaged app did not remain running after LaunchServices launch.")
        }
        let binary = appURL.appendingPathComponent("Contents/MacOS/FigureAssembly")
        let digest = SHA256.hash(data: try Data(contentsOf: binary)).map { String(format: "%02x", $0) }.joined()
        let report: [String: Any] = ["status": "PASS", "app": appURL.path, "processIdentifier": running.processIdentifier,
                                     "finishedLaunching": true, "binarySHA256": digest,
                                     "scope": "Public LaunchServices app launch, same native route as opening the .app; no human double-click claim."]
        guard running.terminate() else { throw NativeFailure("quit_failed", "The clean packaged app did not accept normal termination.") }
        for _ in 0..<30 {
            if running.isTerminated { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        guard running.isTerminated else { throw NativeFailure("quit_failed", "The clean packaged app did not quit.") }
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: reportURL)
        print("PASS packaged .app LaunchServices launch and normal clean quit")
    }
}
