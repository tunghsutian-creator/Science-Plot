import AppKit
import UniformTypeIdentifiers

@MainActor
protocol NativeDialogs: AnyObject {
    var window: NSWindow? { get set }
    func importFiles() async throws -> [URL]
    func openProject() async throws -> URL?
    func saveFile(name: String, type: UTType) async throws -> URL?
}

@MainActor
final class SystemDialogs: NativeDialogs {
    weak var window: NSWindow?
    private var busy = false

    func importFiles() async throws -> [URL] {
        let window = try begin(); defer { busy = false }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.pdf, .png, .jpeg, .tiff]
        panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        return await panel.beginSheetModal(for: window) == .OK ? panel.urls : []
    }

    func openProject() async throws -> URL? {
        let window = try begin(); defer { busy = false }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "figureassembly") ?? .json]
        panel.canChooseDirectories = false
        return await panel.beginSheetModal(for: window) == .OK ? panel.url : nil
    }

    func saveFile(name: String, type: UTType) async throws -> URL? {
        let window = try begin(); defer { busy = false }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [type]; panel.nameFieldStringValue = name
        panel.canCreateDirectories = true; panel.isExtensionHidden = false
        return await panel.beginSheetModal(for: window) == .OK ? panel.url : nil
    }

    private func begin() throws -> NSWindow {
        guard let window else { throw NativeFailure("window_closed", "The document window is closed.") }
        guard !busy else { throw NativeFailure("dialog_open", "Finish the current file dialog first.") }
        busy = true
        return window
    }
}
